import json
import uuid
import functools
from concurrent.futures import ThreadPoolExecutor

import pytest
from unittest import mock

from django.conf import settings
from django.test import override_settings

import aioboto3
import pytest_asyncio
from asgiref.sync import sync_to_async
from dlt.common.configuration.specs.aws_credentials import AwsCredentials
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.schema import HogQLQueryResponse

from posthog.hogql.query import execute_hogql_query

from posthog.temporal.data_imports.external_data_job import ExternalDataJobWorkflow
from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import DeltaTableHelper
from posthog.temporal.data_imports.settings import ACTIVITIES
from posthog.temporal.utils import ExternalDataWorkflowInputs

from products.data_warehouse.backend.models import ExternalDataJob
from products.data_warehouse.backend.models.external_data_job import get_latest_run_if_exists
from products.data_warehouse.backend.models.external_table_definitions import external_tables

BUCKET_NAME = "test-pipeline"
SESSION = aioboto3.Session()
create_test_client = functools.partial(SESSION.client, endpoint_url=settings.OBJECT_STORAGE_ENDPOINT)


@pytest_asyncio.fixture
async def minio_client():
    """Manage an S3 client to interact with a MinIO bucket.

    Yields the client after creating a bucket. Upon resuming, we delete
    the contents and the bucket itself.
    """
    async with create_test_client(
        "s3",
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
    ) as minio_client:
        try:
            await minio_client.head_bucket(Bucket=BUCKET_NAME)
        except:
            await minio_client.create_bucket(Bucket=BUCKET_NAME)

        yield minio_client


def _mock_to_session_credentials(class_self):
    return {
        "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
        "aws_session_token": None,
        "AWS_ALLOW_HTTP": "true",
        "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
    }


def _mock_to_object_store_rs_credentials(class_self):
    return {
        "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
        "region": "us-east-1",
        "AWS_ALLOW_HTTP": "true",
        "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
    }


async def run_external_data_job_workflow(
    team,
    external_data_source,
    external_data_schema,
    table_name,
    expected_rows_synced: int | None,
    expected_total_rows: int | None,
    expected_columns: list[str] | None = None,
) -> HogQLQueryResponse:
    workflow_id = str(uuid.uuid4())
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=external_data_source.pk,
        external_data_schema_id=external_data_schema.id,
        billable=False,
    )

    with (
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            BUCKET_PATH=BUCKET_NAME,
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_REGION="us-east-1",
            AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        mock.patch.object(DeltaTableHelper, "compact_table") as mock_compact_table,
        mock.patch(
            "posthog.temporal.data_imports.external_data_job.get_data_import_finished_metric"
        ) as mock_get_data_import_finished_metric,
        # make sure intended error of line 175 in posthog/warehouse/models/table.py doesn't trigger flag calls
        mock.patch("posthoganalytics.capture_exception", return_value=None),
        mock.patch.object(AwsCredentials, "to_session_credentials", _mock_to_session_credentials),
        mock.patch.object(AwsCredentials, "to_object_store_rs_credentials", _mock_to_object_store_rs_credentials),
    ):
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                workflows=[ExternalDataJobWorkflow],
                activities=ACTIVITIES,  # type: ignore
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=50),
                max_concurrent_activities=50,
            ):
                await activity_environment.client.execute_workflow(
                    ExternalDataJobWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    # if not ignore_assertions:
    run: ExternalDataJob = await get_latest_run_if_exists(team_id=team.pk, pipeline_id=external_data_source.pk)

    assert run is not None
    assert run.status == ExternalDataJob.Status.COMPLETED
    if expected_rows_synced is not None:
        assert run.rows_synced == expected_rows_synced

    mock_compact_table.assert_called()
    mock_get_data_import_finished_metric.assert_called_with(
        source_type=external_data_source.source_type, status=ExternalDataJob.Status.COMPLETED.lower()
    )

    await external_data_schema.arefresh_from_db()

    assert external_data_schema.last_synced_at == run.created_at

    if expected_columns is None:
        columns_str = "*"
    else:
        columns_str = ", ".join(expected_columns)

    res = await sync_to_async(execute_hogql_query)(f"SELECT {columns_str} FROM {table_name}", team)
    if expected_total_rows is not None:
        assert len(res.results) == expected_total_rows
    if expected_columns is not None:
        assert set(expected_columns) == set(res.columns or [])

    if table_name in external_tables:
        table_columns = [name for name, field in external_tables.get(table_name, {}).items() if not field.hidden]
        assert set(table_columns) == set(res.columns or [])

    await external_data_schema.arefresh_from_db()
    assert external_data_schema.sync_type_config.get("reset_pipeline") is None
    return res


@pytest.fixture
def stripe_balance_transaction():
    return json.loads(
        """
        {
            "object": "list",
            "url": "/v1/balance_transactions",
            "has_more": false,
            "data": [
                {
                    "id": "txn_1MiN3gLkdIwHu7ixxapQrznl",
                    "object": "balance_transaction",
                    "amount": -400,
                    "available_on": 1678043844,
                    "created": 1678043844,
                    "currency": "usd",
                    "description": null,
                    "exchange_rate": null,
                    "fee": 0,
                    "fee_details": [],
                    "net": -400,
                    "reporting_category": "transfer",
                    "source": "tr_1MiN3gLkdIwHu7ixNCZvFdgA",
                    "status": "available",
                    "type": "transfer"
                }
            ]
        }
        """
    )


@pytest.fixture
def stripe_charge():
    return json.loads(
        """
        {
            "object": "list",
            "url": "/v1/charges",
            "has_more": false,
            "data": [
                {
                    "id": "ch_3MmlLrLkdIwHu7ix0snN0B15",
                    "object": "charge",
                    "amount": 1099,
                    "amount_captured": 1099,
                    "amount_refunded": 0,
                    "application": null,
                    "application_fee": null,
                    "application_fee_amount": null,
                    "balance_transaction": "txn_3MmlLrLkdIwHu7ix0uke3Ezy",
                    "billing_details": {
                        "address": {
                        "city": null,
                        "country": null,
                        "line1": null,
                        "line2": null,
                        "postal_code": null,
                        "state": null
                        },
                        "email": null,
                        "name": null,
                        "phone": null
                    },
                    "calculated_statement_descriptor": "Stripe",
                    "captured": true,
                    "created": 1679090539,
                    "currency": "usd",
                    "customer": null,
                    "description": null,
                    "disputed": false,
                    "failure_balance_transaction": null,
                    "failure_code": null,
                    "failure_message": null,
                    "fraud_details": {},
                    "invoice": null,
                    "livemode": false,
                    "metadata": {},
                    "on_behalf_of": null,
                    "outcome": {
                        "network_status": "approved_by_network",
                        "reason": null,
                        "risk_level": "normal",
                        "risk_score": 32,
                        "seller_message": "Payment complete.",
                        "type": "authorized"
                    },
                    "paid": true,
                    "payment_intent": null,
                    "payment_method": "card_1MmlLrLkdIwHu7ixIJwEWSNR",
                    "payment_method_details": {
                        "card": {
                        "brand": "visa",
                        "checks": {
                            "address_line1_check": null,
                            "address_postal_code_check": null,
                            "cvc_check": null
                        },
                        "country": "US",
                        "exp_month": 3,
                        "exp_year": 2024,
                        "fingerprint": "mToisGZ01V71BCos",
                        "funding": "credit",
                        "installments": null,
                        "last4": "4242",
                        "mandate": null,
                        "network": "visa",
                        "three_d_secure": null,
                        "wallet": null
                        },
                        "type": "card"
                    },
                    "receipt_email": null,
                    "receipt_number": null,
                    "receipt_url": "https://pay.stripe.com/receipts/payment/CAcaFwoVYWNjdF8xTTJKVGtMa2RJd0h1N2l4KOvG06AGMgZfBXyr1aw6LBa9vaaSRWU96d8qBwz9z2J_CObiV_H2-e8RezSK_sw0KISesp4czsOUlVKY",
                    "refunded": false,
                    "review": null,
                    "shipping": null,
                    "source_transfer": null,
                    "statement_descriptor": null,
                    "statement_descriptor_suffix": null,
                    "status": "succeeded",
                    "transfer_data": null,
                    "transfer_group": null
                }
            ]
        }
        """
    )


@pytest.fixture
def stripe_customer():
    return json.loads(
        """
        {
            "object": "list",
            "url": "/v1/customers",
            "has_more": false,
            "data": [
                {
                    "id": "cus_NffrFeUfNV2Hib",
                    "object": "customer",
                    "address": null,
                    "balance": 0,
                    "created": 1680893993,
                    "currency": null,
                    "default_source": null,
                    "delinquent": false,
                    "description": null,
                    "discount": null,
                    "email": "jennyrosen@example.com",
                    "invoice_prefix": "0759376C",
                    "invoice_settings": {
                        "custom_fields": null,
                        "default_payment_method": null,
                        "footer": null,
                        "rendering_options": null
                    },
                    "livemode": false,
                    "metadata": {},
                    "name": "Jenny Rosen",
                    "next_invoice_sequence": 1,
                    "phone": null,
                    "preferred_locales": [],
                    "shipping": null,
                    "tax_exempt": "none",
                    "test_clock": null
                }
            ]
        }
        """
    )


@pytest.fixture
def stripe_invoice():
    return json.loads(
        """
        {
            "object": "list",
            "url": "/v1/invoices",
            "has_more": false,
            "data": [
                {
                    "id": "in_1MtHbELkdIwHu7ixl4OzzPMv",
                    "object": "invoice",
                    "account_country": "US",
                    "account_name": "Stripe Docs",
                    "account_tax_ids": null,
                    "amount_due": 0,
                    "amount_paid": 0,
                    "amount_remaining": 0,
                    "amount_shipping": 0,
                    "application": null,
                    "application_fee_amount": null,
                    "attempt_count": 0,
                    "attempted": false,
                    "auto_advance": false,
                    "automatic_tax": {
                        "enabled": false,
                        "liability": null,
                        "status": null
                    },
                    "billing_reason": "manual",
                    "charge": null,
                    "collection_method": "charge_automatically",
                    "created": 1680644467,
                    "currency": "usd",
                    "custom_fields": null,
                    "customer": "cus_NeZwdNtLEOXuvB",
                    "customer_address": null,
                    "customer_email": "jennyrosen@example.com",
                    "customer_name": "Jenny Rosen",
                    "customer_phone": null,
                    "customer_shipping": null,
                    "customer_tax_exempt": "none",
                    "customer_tax_ids": [],
                    "default_payment_method": null,
                    "default_source": null,
                    "default_tax_rates": [],
                    "description": null,
                    "discount": null,
                    "discounts": [],
                    "due_date": null,
                    "ending_balance": null,
                    "footer": null,
                    "from_invoice": null,
                    "hosted_invoice_url": null,
                    "invoice_pdf": null,
                    "issuer": {
                        "type": "self"
                    },
                    "last_finalization_error": null,
                    "latest_revision": null,
                    "lines": {
                        "object": "list",
                        "data": [],
                        "has_more": false,
                        "total_count": 0,
                        "url": "/v1/invoices/in_1MtHbELkdIwHu7ixl4OzzPMv/lines"
                    },
                    "livemode": false,
                    "metadata": {},
                    "next_payment_attempt": null,
                    "number": null,
                    "on_behalf_of": null,
                    "paid": false,
                    "paid_out_of_band": false,
                    "payment_intent": null,
                    "payment_settings": {
                        "default_mandate": null,
                        "payment_method_options": null,
                        "payment_method_types": null
                    },
                    "period_end": 1680644467,
                    "period_start": 1680644467,
                    "post_payment_credit_notes_amount": 0,
                    "pre_payment_credit_notes_amount": 0,
                    "quote": null,
                    "receipt_number": null,
                    "rendering_options": null,
                    "shipping_cost": null,
                    "shipping_details": null,
                    "starting_balance": 0,
                    "statement_descriptor": null,
                    "status": "draft",
                    "status_transitions": {
                        "finalized_at": null,
                        "marked_uncollectible_at": null,
                        "paid_at": null,
                        "voided_at": null
                    },
                    "subscription": null,
                    "subtotal": 0,
                    "subtotal_excluding_tax": 0,
                    "tax": null,
                    "test_clock": null,
                    "total": 0,
                    "total_discount_amounts": [],
                    "total_excluding_tax": 0,
                    "total_tax_amounts": [],
                    "transfer_data": null,
                    "webhooks_delivered_at": 1680644467
                }
            ]
        }
        """
    )


@pytest.fixture
def stripe_price():
    return json.loads(
        """
        {
            "object": "list",
            "url": "/v1/prices",
            "has_more": false,
            "data": [
                {
                    "id": "price_1MoBy5LkdIwHu7ixZhnattbh",
                    "object": "price",
                    "active": true,
                    "billing_scheme": "per_unit",
                    "created": 1679431181,
                    "currency": "usd",
                    "custom_unit_amount": null,
                    "livemode": false,
                    "lookup_key": null,
                    "metadata": {},
                    "nickname": null,
                    "product": "prod_NZKdYqrwEYx6iK",
                    "recurring": {
                        "aggregate_usage": null,
                        "interval": "month",
                        "interval_count": 1,
                        "trial_period_days": null,
                        "usage_type": "licensed"
                    },
                    "tax_behavior": "unspecified",
                    "tiers_mode": null,
                    "transform_quantity": null,
                    "type": "recurring",
                    "unit_amount": 1000,
                    "unit_amount_decimal": "1000"
                }
            ]
        }
        """
    )


@pytest.fixture
def stripe_product():
    return json.loads(
        """
        {
            "object": "list",
            "url": "/v1/products",
            "has_more": false,
            "data": [
                {
                    "id": "prod_NWjs8kKbJWmuuc",
                    "object": "product",
                    "active": true,
                    "created": 1678833149,
                    "default_price": null,
                    "description": null,
                    "images": [],
                    "features": [],
                    "livemode": false,
                    "metadata": {},
                    "name": "Gold Plan",
                    "package_dimensions": null,
                    "shippable": null,
                    "statement_descriptor": null,
                    "tax_code": null,
                    "unit_label": null,
                    "updated": 1678833149,
                    "url": null
                }
            ]
        }
        """
    )


@pytest.fixture
def stripe_subscription():
    return json.loads(
        """
        {
            "object": "list",
            "url": "/v1/subscriptions",
            "has_more": false,
            "data": [
                {
                    "id": "sub_1MowQVLkdIwHu7ixeRlqHVzs",
                    "object": "subscription",
                    "application": null,
                    "application_fee_percent": null,
                    "automatic_tax": {
                        "enabled": false,
                        "liability": null
                    },
                    "billing_cycle_anchor": 1679609767,
                    "billing_thresholds": null,
                    "cancel_at": null,
                    "cancel_at_period_end": false,
                    "canceled_at": null,
                    "cancellation_details": {
                        "comment": null,
                        "feedback": null,
                        "reason": null
                    },
                    "collection_method": "charge_automatically",
                    "created": 1679609767,
                    "currency": "usd",
                    "current_period_end": 1682288167,
                    "current_period_start": 1679609767,
                    "customer": "cus_Na6dX7aXxi11N4",
                    "days_until_due": null,
                    "default_payment_method": null,
                    "default_source": null,
                    "default_tax_rates": [],
                    "description": null,
                    "discount": null,
                    "discounts": null,
                    "ended_at": null,
                    "invoice_settings": {
                        "issuer": {
                        "type": "self"
                        }
                    },
                    "items": {
                        "object": "list",
                        "data": [
                        {
                            "id": "si_Na6dzxczY5fwHx",
                            "object": "subscription_item",
                            "billing_thresholds": null,
                            "created": 1679609768,
                            "metadata": {},
                            "plan": {
                            "id": "price_1MowQULkdIwHu7ixraBm864M",
                            "object": "plan",
                            "active": true,
                            "aggregate_usage": null,
                            "amount": 1000,
                            "amount_decimal": "1000",
                            "billing_scheme": "per_unit",
                            "created": 1679609766,
                            "currency": "usd",
                            "discounts": null,
                            "interval": "month",
                            "interval_count": 1,
                            "livemode": false,
                            "metadata": {},
                            "nickname": null,
                            "product": "prod_Na6dGcTsmU0I4R",
                            "tiers_mode": null,
                            "transform_usage": null,
                            "trial_period_days": null,
                            "usage_type": "licensed"
                            },
                            "price": {
                            "id": "price_1MowQULkdIwHu7ixraBm864M",
                            "object": "price",
                            "active": true,
                            "billing_scheme": "per_unit",
                            "created": 1679609766,
                            "currency": "usd",
                            "custom_unit_amount": null,
                            "livemode": false,
                            "lookup_key": null,
                            "metadata": {},
                            "nickname": null,
                            "product": "prod_Na6dGcTsmU0I4R",
                            "recurring": {
                                "aggregate_usage": null,
                                "interval": "month",
                                "interval_count": 1,
                                "trial_period_days": null,
                                "usage_type": "licensed"
                            },
                            "tax_behavior": "unspecified",
                            "tiers_mode": null,
                            "transform_quantity": null,
                            "type": "recurring",
                            "unit_amount": 1000,
                            "unit_amount_decimal": "1000"
                            },
                            "quantity": 1,
                            "subscription": "sub_1MowQVLkdIwHu7ixeRlqHVzs",
                            "tax_rates": []
                        }
                        ],
                        "has_more": false,
                        "total_count": 1,
                        "url": "/v1/subscription_items?subscription=sub_1MowQVLkdIwHu7ixeRlqHVzs"
                    },
                    "latest_invoice": "in_1MowQWLkdIwHu7ixuzkSPfKd",
                    "livemode": false,
                    "metadata": {},
                    "next_pending_invoice_item_invoice": null,
                    "on_behalf_of": null,
                    "pause_collection": null,
                    "payment_settings": {
                        "payment_method_options": null,
                        "payment_method_types": null,
                        "save_default_payment_method": "off"
                    },
                    "pending_invoice_item_interval": null,
                    "pending_setup_intent": null,
                    "pending_update": null,
                    "schedule": null,
                    "start_date": 1679609767,
                    "status": "active",
                    "test_clock": null,
                    "transfer_data": null,
                    "trial_end": null,
                    "trial_settings": {
                        "end_behavior": {
                        "missing_payment_method": "create_invoice"
                        }
                    },
                    "trial_start": null
                }
            ]
        }
        """
    )


@pytest.fixture
def stripe_dispute():
    return json.loads(
        """
        {
            "object": "list",
            "url": "/v1/disputes",
            "has_more": false,
            "data": [
                {
                    "id": "dp_1MtHbELkdIwHu7ixl4OzzPMv",
                    "object": "dispute",
                    "amount": 1000,
                    "balance_transactions": [],
                    "charge": "ch_1MtHbELkdIwHu7ixl4OzzPMv",
                    "created": 1680644467,
                    "currency": "usd",
                    "evidence": {
                        "access_activity_log": null,
                        "billing_address": null,
                        "cancellation_policy": null,
                        "cancellation_policy_disclosure": null,
                        "cancellation_rebuttal": null,
                        "customer_communication": null,
                        "customer_email_address": "customer@example.com",
                        "customer_name": "John Doe",
                        "customer_purchase_ip": null,
                        "customer_signature": null,
                        "duplicate_charge_documentation": null,
                        "duplicate_charge_explanation": null,
                        "duplicate_charge_id": null,
                        "product_description": null,
                        "receipt": null,
                        "refund_policy": null,
                        "refund_policy_disclosure": null,
                        "refund_refusal_explanation": null,
                        "service_date": null,
                        "service_documentation": null,
                        "shipping_address": null,
                        "shipping_carrier": null,
                        "shipping_date": null,
                        "shipping_documentation": null,
                        "shipping_tracking_number": null,
                        "uncategorized_file": null,
                        "uncategorized_text": null
                    },
                    "evidence_details": {
                        "due_by": 1681249267,
                        "has_evidence": false,
                        "past_due": false,
                        "submission_count": 0
                    },
                    "is_charge_refundable": true,
                    "livemode": false,
                    "metadata": {},
                    "network_reason_code": "4855",
                    "payment_intent": "pi_1MtHbELkdIwHu7ixl4OzzPMv",
                    "reason": "fraudulent",
                    "status": "warning_needs_response"
                }
            ]
        }
        """
    )


@pytest.fixture
def stripe_payout():
    return json.loads(
        """
        {
            "object": "list",
            "url": "/v1/payouts",
            "has_more": false,
            "data": [
                {
                    "id": "po_1MtHbELkdIwHu7ixl4OzzPMv",
                    "object": "payout",
                    "amount": 2000,
                    "arrival_date": 1680648000,
                    "automatic": true,
                    "balance_transaction": "txn_1MtHbELkdIwHu7ixl4OzzPMv",
                    "created": 1680644467,
                    "currency": "usd",
                    "description": "STRIPE PAYOUT",
                    "destination": "ba_1MtHbELkdIwHu7ixl4OzzPMv",
                    "failure_balance_transaction": null,
                    "failure_code": null,
                    "failure_message": null,
                    "livemode": false,
                    "metadata": {},
                    "method": "standard",
                    "original_payout": null,
                    "reconciliation_status": "completed",
                    "reversed_by": null,
                    "source_type": "card",
                    "statement_descriptor": null,
                    "status": "paid",
                    "type": "bank_account"
                }
            ]
        }
        """
    )


@pytest.fixture
def stripe_refund():
    return json.loads(
        """
        {
            "object": "list",
            "url": "/v1/refunds",
            "has_more": false,
            "data": [
                {
                    "id": "re_1MtHbELkdIwHu7ixl4OzzPMv",
                    "object": "refund",
                    "amount": 500,
                    "balance_transaction": "txn_1MtHbELkdIwHu7ixl4OzzPMv",
                    "charge": "ch_1MtHbELkdIwHu7ixl4OzzPMv",
                    "created": 1680644467,
                    "currency": "usd",
                    "description": null,
                    "failure_balance_transaction": null,
                    "failure_reason": null,
                    "instructions_email": null,
                    "metadata": {},
                    "next_action": null,
                    "payment_intent": "pi_1MtHbELkdIwHu7ixl4OzzPMv",
                    "reason": "requested_by_customer",
                    "receipt_number": null,
                    "source_transfer_reversal": null,
                    "status": "succeeded",
                    "transfer_reversal": null
                }
            ]
        }
        """
    )


@pytest.fixture
def stripe_invoiceitem():
    return json.loads(
        """
        {
            "object": "list",
            "url": "/v1/invoiceitems",
            "has_more": false,
            "data": [
                {
                    "id": "ii_1MtHbELkdIwHu7ixl4OzzPMv",
                    "object": "invoiceitem",
                    "amount": 1500,
                    "currency": "usd",
                    "customer": "cus_NffrFeUfNV2Hib",
                    "date": 1680644467,
                    "description": "One-time setup fee",
                    "discountable": true,
                    "discounts": [],
                    "invoice": null,
                    "livemode": false,
                    "metadata": {},
                    "period": {
                        "end": 1680644467,
                        "start": 1680644467
                    },
                    "price": {
                        "id": "price_1MtHbELkdIwHu7ixl4OzzPMv",
                        "object": "price",
                        "active": true,
                        "billing_scheme": "per_unit",
                        "created": 1680644467,
                        "currency": "usd",
                        "livemode": false,
                        "lookup_key": null,
                        "metadata": {},
                        "nickname": null,
                        "product": "prod_NffrFeUfNV2Hib",
                        "recurring": null,
                        "tax_behavior": "unspecified",
                        "tiers_mode": null,
                        "transform_quantity": null,
                        "type": "one_time",
                        "unit_amount": 1500,
                        "unit_amount_decimal": "1500"
                    },
                    "proration": false,
                    "quantity": 1,
                    "subscription": null,
                    "tax_rates": [],
                    "test_clock": null,
                    "unit_amount": 1500,
                    "unit_amount_decimal": "1500"
                }
            ]
        }
        """
    )


@pytest.fixture
def stripe_credit_note():
    return json.loads(
        """
        {
            "object": "list",
            "url": "/v1/credit_notes",
            "has_more": false,
            "data": [
                {
                    "id": "cn_1MtHbELkdIwHu7ixl4OzzPMv",
                    "object": "credit_note",
                    "amount": 1000,
                    "currency": "usd",
                    "customer": "cus_NffrFeUfNV2Hib",
                    "created": 1680644467,
                    "discount_amount": 0,
                    "discount_amounts": [],
                    "invoice": "in_1MtHbELkdIwHu7ixl4OzzPMv",
                    "lines": {
                        "object": "list",
                        "data": [
                            {
                                "id": "cnli_1MtHbELkdIwHu7ixl4OzzPMv",
                                "object": "credit_note_line_item",
                                "amount": 1000,
                                "description": "Credit for returned item",
                                "discount_amount": 0,
                                "discount_amounts": [],
                                "invoice_line_item": "il_1MtHbELkdIwHu7ixl4OzzPMv",
                                "livemode": false,
                                "quantity": 1,
                                "tax_amounts": [],
                                "tax_rates": [],
                                "type": "invoice_line_item",
                                "unit_amount": 1000,
                                "unit_amount_decimal": "1000"
                            }
                        ],
                        "has_more": false,
                        "total_count": 1,
                        "url": "/v1/credit_notes/cn_1MtHbELkdIwHu7ixl4OzzPMv/lines"
                    },
                    "livemode": false,
                    "memo": "Credit for returned item",
                    "metadata": {},
                    "number": "ABCD-1234",
                    "out_of_band_amount": null,
                    "pdf": "https://pay.stripe.com/credit_notes/cn_1MtHbELkdIwHu7ixl4OzzPMv/pdf",
                    "reason": "duplicate",
                    "refund": null,
                    "status": "issued",
                    "subtotal": 1000,
                    "tax_amounts": [],
                    "total": 1000,
                    "type": "post_payment",
                    "voided_at": null
                }
            ]
        }
        """
    )


@pytest.fixture
def stripe_customer_balance_transaction():
    return json.loads(
        """
        {
            "object": "list",
            "url": "/v1/credit_notes",
            "has_more": false,
            "data": [
                {
                    "amount": 123,
                    "checkout_session": null,
                    "created": 1744275509,
                    "credit_note": null,
                    "currency": "usd",
                    "customer": "cus_OyUnzb0sjasdsd",
                    "description": "Credit expired",
                    "ending_balance": 0,
                    "id": "cbtxn_1RCGwLEuIatRXSdz53OwYsdfsd",
                    "invoice_id": null,
                    "livemode": true,
                    "metadata": {},
                    "object": "customer_balance_transaction",
                    "type": "adjustment"
                }
            ]
        }
        """
    )


@pytest.fixture
def stripe_customer_payment_method():
    return json.loads(
        """
        {
            "object": "list",
            "url": "/v1/payment_methods",
            "has_more": false,
            "data": [
                {
                    "id": "pm_1MtHbELkdIwHu7ixl4OzzPMv",
                    "object": "payment_method",
                    "customer": "cus_NffrFeUfNV2Hib",
                    "created": 1680644467,
                    "livemode": false,
                    "redaction": {
                        "reason": "duplicate"
                    },
                    "metadata": {},
                    "billing_details": {
                        "address": {
                            "city": "San Francisco",
                            "country": "US",
                            "line1": "510 Townsend St",
                            "line2": "Apt 345",
                            "postal_code": "94103",
                            "state": "CA"
                        },
                        "email": "test@example.com",
                        "name": "Test test",
                        "phone": "+15555555555"
                    },
                    "card": {
                        "brand": "visa",
                        "last4": "4242",
                        "exp_month": 12,
                        "exp_year": 2024,
                        "fingerprint": "mToisGZ01V71BCos"
                    },
                    "type": "card"
                }
            ]
        }
        """
    )


@pytest.fixture
def zendesk_brands():
    return json.loads(
        """
        {
            "brands": [
                {
                    "active": true,
                    "brand_url": "https://brand1.zendesk.com",
                    "created_at": "2019-08-06T02:43:39Z",
                    "default": true,
                    "has_help_center": true,
                    "help_center_state": "enabled",
                    "host_mapping": "brand1.com",
                    "id": 360002783572,
                    "is_deleted": false,
                    "logo": {
                        "content_type": "image/png",
                        "content_url": "https://company.zendesk.com/logos/brand1_logo.png",
                        "file_name": "brand1_logo.png",
                        "id": 928374,
                        "mapped_content_url": "https://company.com/logos/brand1_logo.png",
                        "size": 166144,
                        "thumbnails": [
                            {
                                "content_type": "image/png",
                                "content_url": "https://company.zendesk.com/photos/brand1_logo_thumb.png",
                                "file_name": "brand1_logo_thumb.png",
                                "id": 928375,
                                "mapped_content_url": "https://company.com/photos/brand1_logo_thumb.png",
                                "size": 58298,
                                "url": "https://company.zendesk.com/api/v2/attachments/928375.json"
                            },
                            {
                                "content_type": "image/png",
                                "content_url": "https://company.zendesk.com/photos/brand1_logo_small.png",
                                "file_name": "brand1_logo_small.png",
                                "id": 928376,
                                "mapped_content_url": "https://company.com/photos/brand1_logo_small.png",
                                "size": 58298,
                                "url": "https://company.zendesk.com/api/v2/attachments/928376.json"
                            }
                        ],
                        "url": "https://company.zendesk.com/api/v2/attachments/928374.json"
                    },
                    "name": "Brand 1",
                    "signature_template": "{{agent.signature}}",
                    "subdomain": "hello-world",
                    "ticket_form_ids": [
                        360000660811
                    ],
                    "updated_at": "2019-08-06T02:43:40Z",
                    "url": "https://company.zendesk.com/api/v2/brands/360002783572.json"
                }
            ],
            "count": 1,
            "next_page": null,
            "previous_page": null
        }
        """
    )


@pytest.fixture
def zendesk_organizations():
    return json.loads(
        """
        {
            "count": 1,
            "next_page": null,
            "organizations": [
                {
                    "created_at": "2018-11-14T00:14:52Z",
                    "details": "caterpillar =)",
                    "domain_names": [
                        "remain.com"
                    ],
                    "external_id": "ABC198",
                    "group_id": 1835962,
                    "id": 4112492,
                    "name": "Groablet Enterprises",
                    "notes": "donkey",
                    "organization_fields": {
                        "datepudding": "2018-11-04T00:00:00+00:00",
                        "org_field_1": "happy happy",
                        "org_field_2": "teapot_kettle"
                    },
                    "shared_comments": false,
                    "shared_tickets": false,
                    "tags": [
                        "smiley",
                        "teapot_kettle"
                    ],
                    "updated_at": "2018-11-14T00:54:22Z",
                    "url": "https://example.zendesk.com/api/v2/organizations/4112492.json"
                }
            ],
            "previous_page": null
        }
        """
    )


@pytest.fixture
def zendesk_groups():
    return json.loads(
        """
        {
            "groups": [
                {
                    "id": 211,
                    "url": "https://test.zendesk.com/api/v2/groups/211.json",
                    "name": "DJs",
                    "description": "Peeps who DJ",
                    "default": false,
                    "is_public": true,
                    "deleted": true,
                    "created_at": "2009-05-13T00:07:08Z",
                    "updated_at": "2011-07-22T00:11:12Z"
                }
            ]
        }
        """
    )


@pytest.fixture
def zendesk_sla_policies():
    return json.loads(
        """
        {
            "count": 1,
            "next_page": null,
            "previous_page": null,
            "sla_policies": [
                {
                "description": "For urgent incidents, we will respond to tickets in 10 minutes",
                "filter": {
                    "all": [
                        {
                            "field": "type",
                            "operator": "is",
                            "value": "incident"
                        },
                        {
                            "field": "via_id",
                            "operator": "is",
                            "value": "4"
                        }
                    ],
                    "any": []
                },
                "id": 36,
                "policy_metrics": [
                    {
                        "business_hours": false,
                        "metric": "first_reply_time",
                        "priority": "low",
                        "target": 60
                    }
                ],
                "position": 3,
                "title": "Incidents",
                "url": "https://{subdomain}.zendesk.com/api/v2/slas/policies/36.json"
                }
            ]
        }
        """
    )


@pytest.fixture
def zendesk_users():
    return json.loads(
        """
        {
            "users": [
                {
                    "id": 1268829372990,
                    "url": "https://test.zendesk.com/api/v2/users/1268829372990.json",
                    "name": "Test",
                    "email": "test@posthog.com",
                    "created_at": "2022-04-25T19:42:18Z",
                    "updated_at": "2024-05-31T22:10:48Z",
                    "time_zone": "UTC",
                    "iana_time_zone": "Etc/UTC",
                    "phone": null,
                    "shared_phone_number": null,
                    "photo": null,
                    "locale_id": 1,
                    "locale": "en-US",
                    "organization_id": 1234568,
                    "role": "end-user",
                    "verified": true,
                    "external_id": null,
                    "tags": [],
                    "alias": "",
                    "active": true,
                    "shared": false,
                    "shared_agent": false,
                    "last_login_at": "2024-02-21T04:13:20Z",
                    "two_factor_auth_enabled": null,
                    "signature": null,
                    "details": "",
                    "notes": "",
                    "role_type": null,
                    "custom_role_id": null,
                    "moderator": false,
                    "ticket_restriction": "requested",
                    "only_private_comments": false,
                    "restricted_agent": true,
                    "suspended": false,
                    "default_group_id": null,
                    "report_csv": false,
                    "user_fields": {
                        "anonymize_data": null
                    }
                }
            ],
            "next_page": null,
            "previous_page": null,
            "count": 1
        }
        """
    )


@pytest.fixture
def zendesk_ticket_fields():
    return json.loads(
        """
        {
            "ticket_fields": [
                {
                    "active": true,
                    "agent_description": "Agent only description",
                    "collapsed_for_agents": false,
                    "created_at": "2009-07-20T22:55:29Z",
                    "description": "This is the subject field of a ticket",
                    "editable_in_portal": true,
                    "id": 34,
                    "position": 21,
                    "raw_description": "This is the subject field of a ticket",
                    "raw_title": "{{dc.my_title}}",
                    "raw_title_in_portal": "{{dc.my_title_in_portal}}",
                    "regexp_for_validation": null,
                    "required": true,
                    "required_in_portal": true,
                    "tag": null,
                    "title": "Subject",
                    "title_in_portal": "Subject",
                    "type": "subject",
                    "updated_at": "2011-05-05T10:38:52Z",
                    "url": "https://company.zendesk.com/api/v2/ticket_fields/34.json",
                    "visible_in_portal": true
                }
            ]
        }
        """
    )


@pytest.fixture
def zendesk_ticket_events():
    return json.loads(
        """
        {
            "count": 1,
            "end_of_stream": true,
            "end_time": 1601357503,
            "next_page": "https://example.zendesk.com/api/v2/incremental/ticket_events.json?start_time=1601357503",
            "ticket_events": [
                {
                    "id": 926256957613,
                    "instance_id": 1,
                    "metric": "agent_work_time",
                    "ticket_id": 155,
                    "time": "2020-10-26T12:53:12Z",
                    "type": "measure"
                }
            ]
        }
        """
    )


@pytest.fixture
def zendesk_tickets():
    return json.loads(
        """
        {
            "count": 1,
            "end_of_stream": true,
            "end_time": 1390362485,
            "next_page": "https://{subdomain}.zendesk.com/api/v2/incremental/tickets.json?per_page=3&start_time=1390362485",
            "tickets": [
                {
                    "generated_timestamp": 1,
                    "assignee_id": 235323,
                    "collaborator_ids": [
                        35334,
                        234
                    ],
                    "created_at": "2009-07-20T22:55:29Z",
                    "custom_fields": [
                        {
                        "id": 27642,
                        "value": "745"
                        },
                        {
                        "id": 27648,
                        "value": "yes"
                        }
                    ],
                    "description": "The fire is very colorful.",
                    "due_at": null,
                    "external_id": "ahg35h3jh",
                    "follower_ids": [
                        35334,
                        234
                    ],
                    "from_messaging_channel": false,
                    "group_id": 98738,
                    "has_incidents": false,
                    "id": 35436,
                    "organization_id": 509974,
                    "priority": "high",
                    "problem_id": 9873764,
                    "raw_subject": "{{dc.printer_on_fire}}",
                    "recipient": "support@company.com",
                    "requester_id": 20978392,
                    "satisfaction_rating": {
                        "comment": "Great support!",
                        "id": 1234,
                        "score": "good"
                    },
                    "sharing_agreement_ids": [
                        84432
                    ],
                    "status": "open",
                    "subject": "Help, my printer is on fire!",
                    "submitter_id": 76872,
                    "tags": [
                        "enterprise",
                        "other_tag"
                    ],
                    "type": "incident",
                    "updated_at": "2011-05-05T10:38:52Z",
                    "url": "https://company.zendesk.com/api/v2/tickets/35436.json",
                    "via": {
                        "channel": "web"
                    }
                }
            ]
        }
        """
    )


@pytest.fixture
def zendesk_ticket_metric_events():
    return json.loads(
        """
        {
            "count": 1,
            "end_time": 1603716792,
            "next_page": "https://company.zendesk.com/api/v2/incremental/ticket_metric_events.json?start_time=1603716792",
            "ticket_metric_events": [
                {
                    "id": 926232157301,
                    "instance_id": 0,
                    "metric": "agent_work_time",
                    "ticket_id": 155,
                    "time": "2020-10-26T12:53:12Z",
                    "type": "measure"
                }
            ]
        }
        """
    )


@pytest.fixture
def chargebee_customer():
    # note that chargebee actually return both a customer and a card if one is
    # attached (we ignore this when ingesting the data)
    return json.loads(
        """
        {
            "list": [
                {
                    "card": {
                        "card_type": "american_express",
                        "created_at": 1729612767,
                        "customer_id": "cbdemo_douglas",
                        "expiry_month": 5,
                        "expiry_year": 2028,
                        "first_name": "Douglas",
                        "funding_type": "not_known",
                        "gateway": "chargebee",
                        "gateway_account_id": "gw_199Ne4URwspru2qp",
                        "iin": "371449",
                        "last4": "8431",
                        "last_name": "Quaid",
                        "masked_number": "***********8431",
                        "object": "card",
                        "payment_source_id": "pm_19A7lVURwsu9pPnQ",
                        "resource_version": 1729612767061,
                        "status": "valid",
                        "updated_at": 1729612767
                    },
                    "customer": {
                        "allow_direct_debit": false,
                        "auto_collection": "on",
                        "card_status": "valid",
                        "channel": "web",
                        "company": "Greenplus Enterprises",
                        "created_at": 1729612766,
                        "deleted": false,
                        "email": "douglas_AT_test.com@example.com",
                        "excess_payments": 0,
                        "first_name": "Douglas",
                        "id": "cbdemo_douglas",
                        "last_name": "Quaid",
                        "mrr": 0,
                        "net_term_days": 0,
                        "object": "customer",
                        "payment_method": {
                            "gateway": "chargebee",
                            "gateway_account_id": "gw_199Ne4URwspru2qp",
                            "object": "payment_method",
                            "reference_id": "tok_19A7lVURwsu9hPnP",
                            "status": "valid",
                            "type": "card"
                        },
                        "phone": "2344903756",
                        "pii_cleared": "active",
                        "preferred_currency_code": "GBP",
                        "primary_payment_source_id": "pm_19A7lVURwsu9pPnQ",
                        "promotional_credits": 0,
                        "refundable_credits": 0,
                        "resource_version": 1729612767062,
                        "taxability": "taxable",
                        "unbilled_charges": 0,
                        "updated_at": 1729612767
                    }
                }
            ]
        }
        """
    )
