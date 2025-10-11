from posthog.hogql import ast
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DatabaseField,
    DateDatabaseField,
    DateTimeDatabaseField,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringArrayDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
)

from posthog.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY

external_tables: dict[str, dict[str, DatabaseField]] = {
    "*": {
        "__dlt_id": StringDatabaseField(name="_dlt_id", hidden=True),
        "__dlt_load_id": StringDatabaseField(name="_dlt_load_id", hidden=True),
        "__ph_debug": StringJSONDatabaseField(name="_ph_debug", hidden=True),
        f"_{PARTITION_KEY}": StringDatabaseField(name=PARTITION_KEY, hidden=True),
    },
    "stripe_account": {
        "id": StringDatabaseField(name="id"),
        "object": StringDatabaseField(name="object"),
        "business_profile": StringJSONDatabaseField(name="business_profile"),
        "business_type": StringDatabaseField(name="business_type"),
        "capabilities": StringJSONDatabaseField(name="capabilities"),
        "charges_enabled": BooleanDatabaseField(name="charges_enabled"),
        "controller": StringJSONDatabaseField(name="controller"),
        "country": StringDatabaseField(name="country"),
        "__created": IntegerDatabaseField(name="created", hidden=True),
        "created_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__created"])],
                    )
                ],
            ),
            name="created_at",
        ),
        "default_currency": StringDatabaseField(name="default_currency"),
        "details_submitted": BooleanDatabaseField(name="details_submitted"),
        "email": StringDatabaseField(name="email"),
        "external_accounts": StringJSONDatabaseField(name="external_accounts"),
        "future_requirements": StringJSONDatabaseField(name="future_requirements"),
        "login_links": StringJSONDatabaseField(name="login_links"),
        "metadata": StringJSONDatabaseField(name="metadata"),
        "payouts_enabled": BooleanDatabaseField(name="payouts_enabled"),
        "requirements": StringJSONDatabaseField(name="requirements"),
        "settings": StringJSONDatabaseField(name="settings"),
        "tos_acceptance": StringJSONDatabaseField(name="tos_acceptance"),
        "type": StringDatabaseField(name="type"),
    },
    "stripe_creditnote": {
        "id": StringDatabaseField(name="id"),
        "object": StringDatabaseField(name="object"),
        "amount": IntegerDatabaseField(name="amount"),
        "amount_shipping": IntegerDatabaseField(name="amount_shipping"),
        "__created": IntegerDatabaseField(name="created", hidden=True),
        "created_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__created"])],
                    )
                ],
            ),
            name="created_at",
        ),
        "currency": StringDatabaseField(name="currency"),
        "customer_id": StringDatabaseField(name="customer"),
        "customer_balance_transaction": StringDatabaseField(name="customer_balance_transaction"),
        "discount_amount": IntegerDatabaseField(name="discount_amount"),
        "discount_amounts": StringJSONDatabaseField(name="discount_amounts"),
        "invoice_id": StringDatabaseField(name="invoice"),
        "lines": StringJSONDatabaseField(name="lines"),
        "livemode": BooleanDatabaseField(name="livemode"),
        "memo": StringDatabaseField(name="memo"),
        "metadata": StringJSONDatabaseField(name="metadata"),
        "number": StringDatabaseField(name="number"),
        "out_of_band_amount": IntegerDatabaseField(name="out_of_band_amount"),
        "pdf": StringDatabaseField(name="pdf"),
        "pre_payment_amount": IntegerDatabaseField(name="pre_payment_amount"),
        "post_payment_amount": IntegerDatabaseField(name="post_payment_amount"),
        "reason": StringDatabaseField(name="reason"),
        "refunds": StringJSONDatabaseField(name="refunds"),
        "shipping_cost": StringJSONDatabaseField(name="shipping_cost"),
        "status": StringDatabaseField(name="status"),
        "subtotal": IntegerDatabaseField(name="subtotal"),
        "subtotal_excluding_tax": IntegerDatabaseField(name="subtotal_excluding_tax"),
        "total": IntegerDatabaseField(name="total"),
        "total_excluding_tax": IntegerDatabaseField(name="total_excluding_tax"),
        "total_taxes": StringJSONDatabaseField(name="total_taxes"),
        "type": StringDatabaseField(name="type"),
        "__voided_at": IntegerDatabaseField(name="voided_at", hidden=True),
        "voided_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__voided_at"])],
                    )
                ],
            ),
            name="voided_at",
        ),
    },
    "stripe_customer": {
        "id": StringDatabaseField(name="id"),
        "name": StringDatabaseField(name="name"),
        "email": StringDatabaseField(name="email"),
        "phone": StringDatabaseField(name="phone"),
        "object": StringDatabaseField(name="object"),
        "address": StringJSONDatabaseField(name="address"),
        "balance": IntegerDatabaseField(name="balance"),
        "__created": IntegerDatabaseField(name="created", hidden=True),
        "created_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__created"])],
                    )
                ],
            ),
            name="created_at",
        ),
        "currency": StringDatabaseField(name="currency"),
        "discount": StringJSONDatabaseField(name="discount"),
        "livemode": BooleanDatabaseField(name="livemode"),
        "metadata": StringJSONDatabaseField(name="metadata"),
        "shipping": StringJSONDatabaseField(name="shipping"),
        "delinquent": BooleanDatabaseField(name="delinquent"),
        "tax_exempt": StringDatabaseField(name="tax_exempt"),
        "description": StringDatabaseField(name="description"),
        "default_source": StringDatabaseField(name="default_source"),
        "invoice_prefix": StringDatabaseField(name="invoice_prefix"),
        "invoice_settings": StringJSONDatabaseField(name="invoice_settings"),
        "preferred_locales": StringJSONDatabaseField(name="preferred_locales"),
        "next_invoice_sequence": IntegerDatabaseField(name="next_invoice_sequence"),
    },
    "stripe_invoice": {
        "id": StringDatabaseField(name="id"),
        "tax": IntegerDatabaseField(name="tax"),
        "paid": BooleanDatabaseField(name="paid"),
        "lines": StringJSONDatabaseField(name="lines"),
        "total": IntegerDatabaseField(name="total"),
        "charge": StringDatabaseField(name="charge"),
        "issuer": StringJSONDatabaseField(name="issuer"),
        "number": StringDatabaseField(name="number"),
        "object": StringDatabaseField(name="object"),
        "status": StringDatabaseField(name="status"),
        "__created": IntegerDatabaseField(name="created", hidden=True),
        "created_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__created"])],
                    )
                ],
            ),
            name="created_at",
        ),
        "currency": StringDatabaseField(name="currency"),
        "customer_id": StringDatabaseField(name="customer"),
        "discount": StringJSONDatabaseField(name="discount"),
        "due_date": IntegerDatabaseField(name="due_date"),
        "livemode": BooleanDatabaseField(name="livemode"),
        "metadata": StringJSONDatabaseField(name="metadata"),
        "subtotal": IntegerDatabaseField(name="subtotal"),
        "attempted": BooleanDatabaseField(name="attempted"),
        "discounts": StringJSONDatabaseField(name="discounts"),
        "rendering": StringJSONDatabaseField(name="rendering"),
        "amount_due": IntegerDatabaseField(name="amount_due"),
        "__period_start": IntegerDatabaseField(name="period_start", hidden=True),
        "period_start_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__period_start"])],
                    )
                ],
            ),
            name="period_start_at",
        ),
        "__period_end": IntegerDatabaseField(name="period_end", hidden=True),
        "period_end_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__period_end"])],
                    )
                ],
            ),
            name="period_end_at",
        ),
        "amount_paid": IntegerDatabaseField(name="amount_paid"),
        "description": StringDatabaseField(name="description"),
        "invoice_pdf": StringDatabaseField(name="invoice_pdf"),
        "account_name": StringDatabaseField(name="account_name"),
        "auto_advance": BooleanDatabaseField(name="auto_advance"),
        "__effective_at": IntegerDatabaseField(name="effective_at", hidden=True),
        "effective_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__effective_at"])],
                    )
                ],
            ),
            name="effective_at",
        ),
        "subscription_id": StringDatabaseField(name="subscription"),
        "attempt_count": IntegerDatabaseField(name="attempt_count"),
        "automatic_tax": StringJSONDatabaseField(name="automatic_tax"),
        "customer_name": StringDatabaseField(name="customer_name"),
        "billing_reason": StringDatabaseField(name="billing_reason"),
        "customer_email": StringDatabaseField(name="customer_email"),
        "ending_balance": IntegerDatabaseField(name="ending_balance"),
        "payment_intent": StringDatabaseField(name="payment_intent"),
        "account_country": StringDatabaseField(name="account_country"),
        "amount_shipping": IntegerDatabaseField(name="amount_shipping"),
        "amount_remaining": IntegerDatabaseField(name="amount_remaining"),
        "customer_address": StringJSONDatabaseField(name="customer_address"),
        "customer_tax_ids": StringJSONDatabaseField(name="customer_tax_ids"),
        "paid_out_of_band": BooleanDatabaseField(name="paid_out_of_band"),
        "payment_settings": StringJSONDatabaseField(name="payment_settings"),
        "starting_balance": IntegerDatabaseField(name="starting_balance"),
        "collection_method": StringDatabaseField(name="collection_method"),
        "default_tax_rates": StringJSONDatabaseField(name="default_tax_rates"),
        "total_tax_amounts": StringJSONDatabaseField(name="total_tax_amounts"),
        "hosted_invoice_url": StringDatabaseField(name="hosted_invoice_url"),
        "status_transitions": StringJSONDatabaseField(name="status_transitions"),
        "customer_tax_exempt": StringDatabaseField(name="customer_tax_exempt"),
        "total_excluding_tax": IntegerDatabaseField(name="total_excluding_tax"),
        "subscription_details": StringJSONDatabaseField(name="subscription_details"),
        "__webhooks_delivered_at": IntegerDatabaseField(name="webhooks_delivered_at", hidden=True),
        "webhooks_delivered_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__webhooks_delivered_at"])],
                    )
                ],
            ),
            name="webhooks_delivered_at",
        ),
        "subtotal_excluding_tax": IntegerDatabaseField(name="subtotal_excluding_tax"),
        "total_discount_amounts": StringJSONDatabaseField(name="total_discount_amounts"),
        "pre_payment_credit_notes_amount": IntegerDatabaseField(name="pre_payment_credit_notes_amount"),
        "post_payment_credit_notes_amount": IntegerDatabaseField(name="post_payment_credit_notes_amount"),
    },
    "stripe_charge": {
        "id": StringDatabaseField(name="id"),
        "paid": BooleanDatabaseField(name="paid"),
        "amount": IntegerDatabaseField(name="amount"),
        "object": StringDatabaseField(name="object"),
        "source": StringJSONDatabaseField(name="source"),
        "status": StringDatabaseField(name="status"),
        "__created": IntegerDatabaseField(name="created", hidden=True),
        "created_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__created"])],
                    )
                ],
            ),
            name="created_at",
        ),
        "invoice_id": StringDatabaseField(name="invoice"),
        "outcome": StringJSONDatabaseField(name="outcome"),
        "captured": BooleanDatabaseField(name="captured"),
        "currency": StringDatabaseField(name="currency"),
        "customer_id": StringDatabaseField(name="customer"),
        "disputed": BooleanDatabaseField(name="disputed"),
        "livemode": BooleanDatabaseField(name="livemode"),
        "metadata": StringJSONDatabaseField(name="metadata"),
        "refunded": BooleanDatabaseField(name="refunded"),
        "description": StringDatabaseField(name="description"),
        "receipt_url": StringDatabaseField(name="receipt_url"),
        "failure_code": StringDatabaseField(name="failure_code"),
        "fraud_details": StringJSONDatabaseField(name="fraud_details"),
        "radar_options": StringJSONDatabaseField(name="radar_options"),
        "receipt_email": StringDatabaseField(name="receipt_email"),
        "payment_intent_id": StringDatabaseField(name="payment_intent"),
        "payment_method_id": StringDatabaseField(name="payment_method"),
        "amount_captured": IntegerDatabaseField(name="amount_captured"),
        "amount_refunded": IntegerDatabaseField(name="amount_refunded"),
        "billing_details": StringJSONDatabaseField(name="billing_details"),
        "failure_message": StringDatabaseField(name="failure_message"),
        "balance_transaction_id": StringDatabaseField(name="balance_transaction"),
        "statement_descriptor": StringDatabaseField(name="statement_descriptor"),
        "payment_method_details": StringJSONDatabaseField(name="payment_method_details"),
        "calculated_statement_descriptor": StringDatabaseField(name="calculated_statement_descriptor"),
    },
    "stripe_price": {
        "id": StringDatabaseField(name="id"),
        "type": StringDatabaseField(name="type"),
        "active": BooleanDatabaseField(name="active"),
        "object": StringDatabaseField(name="object"),
        "__created": IntegerDatabaseField(name="created", hidden=True),
        "created_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__created"])],
                    )
                ],
            ),
            name="created_at",
        ),
        "product_id": StringDatabaseField(name="product"),
        "currency": StringDatabaseField(name="currency"),
        "livemode": BooleanDatabaseField(name="livemode"),
        "metadata": StringJSONDatabaseField(name="metadata"),
        "nickname": StringDatabaseField(name="nickname"),
        "recurring": StringJSONDatabaseField(name="recurring"),
        "tiers_mode": StringDatabaseField(name="tiers_mode"),
        "tiers": StringArrayDatabaseField(name="tiers"),
        "unit_amount": IntegerDatabaseField(name="unit_amount"),
        "tax_behavior": StringDatabaseField(name="tax_behavior"),
        "billing_scheme": StringDatabaseField(name="billing_scheme"),
        "unit_amount_decimal": StringDatabaseField(name="unit_amount_decimal"),
    },
    "stripe_product": {
        "id": StringDatabaseField(name="id"),
        "name": StringDatabaseField(name="name"),
        "type": StringDatabaseField(name="type"),
        "active": BooleanDatabaseField(name="active"),
        "images": StringJSONDatabaseField(name="images"),
        "object": StringDatabaseField(name="object"),
        "__created": IntegerDatabaseField(name="created", hidden=True),
        "created_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__created"])],
                    )
                ],
            ),
            name="created_at",
        ),
        "__updated": IntegerDatabaseField(name="updated", hidden=True),
        "updated_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__updated"])],
                    )
                ],
            ),
            name="updated_at",
        ),
        "features": StringJSONDatabaseField(name="features"),
        "livemode": BooleanDatabaseField(name="livemode"),
        "metadata": StringJSONDatabaseField(name="metadata"),
        "tax_code": StringDatabaseField(name="tax_code"),
        "attributes": StringJSONDatabaseField(name="attributes"),
        "description": StringDatabaseField(name="description"),
        "default_price_id": StringDatabaseField(name="default_price"),
    },
    "stripe_subscription": {
        "id": StringDatabaseField(name="id"),
        "plan": StringJSONDatabaseField(name="plan"),
        "items": StringJSONDatabaseField(name="items"),
        "object": StringDatabaseField(name="object"),
        "status": StringDatabaseField(name="status"),
        "__created": IntegerDatabaseField(name="created", hidden=True),
        "created_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__created"])],
                    )
                ],
            ),
            name="created_at",
        ),
        "currency": StringDatabaseField(name="currency"),
        "customer_id": StringDatabaseField(name="customer"),
        "__ended_at": IntegerDatabaseField(name="ended_at", hidden=True),
        "ended_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__ended_at"])],
                    )
                ],
            ),
            name="ended_at",
        ),
        "livemode": BooleanDatabaseField(name="livemode"),
        "metadata": StringJSONDatabaseField(name="metadata"),
        "quantity": IntegerDatabaseField(name="quantity"),
        "__start_date": IntegerDatabaseField(name="start_date", hidden=True),
        "start_date": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__start_date"])],
                    )
                ],
            ),
            name="start_date",
        ),
        "__canceled_at": IntegerDatabaseField(name="canceled_at", hidden=True),
        "canceled_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__canceled_at"])],
                    )
                ],
            ),
            name="canceled_at",
        ),
        "automatic_tax": StringJSONDatabaseField(name="automatic_tax"),
        "latest_invoice_id": StringDatabaseField(name="latest_invoice"),
        "trial_settings": StringJSONDatabaseField(name="trial_settings"),
        "invoice_settings": StringJSONDatabaseField(name="invoice_settings"),
        "pause_collection": StringJSONDatabaseField(name="pause_collection"),
        "payment_settings": StringJSONDatabaseField(name="payment_settings"),
        "collection_method": StringDatabaseField(name="collection_method"),
        "default_tax_rates": StringJSONDatabaseField(name="default_tax_rates"),
        "__current_period_start": IntegerDatabaseField(name="current_period_start", hidden=True),
        "current_period_start": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__current_period_start"])],
                    )
                ],
            ),
            name="current_period_start",
        ),
        "__current_period_end": IntegerDatabaseField(name="current_period_end", hidden=True),
        "current_period_end": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__current_period_end"])],
                    )
                ],
            ),
            name="current_period_end",
        ),
        "__billing_cycle_anchor": IntegerDatabaseField(name="billing_cycle_anchor", hidden=True),
        "billing_cycle_anchor": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__billing_cycle_anchor"])],
                    )
                ],
            ),
            name="billing_cycle_anchor",
        ),
        "cancel_at_period_end": BooleanDatabaseField(name="cancel_at_period_end"),
        "cancellation_details": StringJSONDatabaseField(name="cancellation_details"),
        "__trial_end": IntegerDatabaseField(name="trial_end", hidden=True),
        "trial_end": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__trial_end"])],
                    )
                ],
            ),
            name="trial_end",
        ),
        "__trial_start": IntegerDatabaseField(name="trial_start", hidden=True),
        "trial_start": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__trial_start"])],
                    )
                ],
            ),
            name="trial_start",
        ),
        "trial_settings": StringJSONDatabaseField(name="trial_settings"),
    },
    "stripe_balancetransaction": {
        "id": StringDatabaseField(name="id"),
        "fee": IntegerDatabaseField(name="fee"),
        "net": IntegerDatabaseField(name="net"),
        "type": StringDatabaseField(name="type"),
        "amount": IntegerDatabaseField(name="amount"),
        "object": StringDatabaseField(name="object"),
        "source_id": StringDatabaseField(name="source"),
        "status": StringDatabaseField(name="status"),
        "__created": IntegerDatabaseField(name="created", hidden=True),
        "created_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__created"])],
                    )
                ],
            ),
            name="created_at",
        ),
        "currency": StringDatabaseField(name="currency"),
        "description": StringDatabaseField(name="description"),
        "fee_details": StringJSONDatabaseField(name="fee_details"),
        "__available_on": IntegerDatabaseField(name="available_on", hidden=True),
        "available_on": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__available_on"])],
                    )
                ],
            ),
            name="available_on",
        ),
        "reporting_category": StringDatabaseField(name="reporting_category"),
    },
    "stripe_dispute": {
        "id": StringDatabaseField(name="id"),
        "object": StringDatabaseField(name="object"),
        "amount": IntegerDatabaseField(name="amount"),
        "charge_id": StringDatabaseField(name="charge"),
        "currency": StringDatabaseField(name="currency"),
        "__created": IntegerDatabaseField(name="created", hidden=True),
        "created_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__created"])],
                    )
                ],
            ),
            name="created_at",
        ),
        "evidence": StringJSONDatabaseField(name="evidence"),
        "evidence_details": StringJSONDatabaseField(name="evidence_details"),
        "is_charge_refundable": BooleanDatabaseField(name="is_charge_refundable"),
        "livemode": BooleanDatabaseField(name="livemode"),
        "metadata": StringJSONDatabaseField(name="metadata"),
        "network_reason_code": StringDatabaseField(name="network_reason_code"),
        "reason": StringDatabaseField(name="reason"),
        "status": StringDatabaseField(name="status"),
        "balance_transactions": StringJSONDatabaseField(name="balance_transactions"),
        "payment_intent_id": StringDatabaseField(name="payment_intent"),
    },
    "stripe_invoiceitem": {
        "id": StringDatabaseField(name="id"),
        "object": StringDatabaseField(name="object"),
        "amount": IntegerDatabaseField(name="amount"),
        "currency": StringDatabaseField(name="currency"),
        "customer_id": StringDatabaseField(name="customer"),
        "__date": IntegerDatabaseField(name="date", hidden=True),
        "date": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__date"])],
                    )
                ],
            ),
            name="date",
        ),
        "description": StringDatabaseField(name="description"),
        "discountable": BooleanDatabaseField(name="discountable"),
        "discounts": StringJSONDatabaseField(name="discounts"),
        "invoice_id": StringDatabaseField(name="invoice"),
        "livemode": BooleanDatabaseField(name="livemode"),
        "metadata": StringJSONDatabaseField(name="metadata"),
        "period": StringJSONDatabaseField(name="period"),
        "price": StringJSONDatabaseField(name="price"),
        "proration": BooleanDatabaseField(name="proration"),
        "quantity": IntegerDatabaseField(name="quantity"),
        "subscription_id": StringDatabaseField(name="subscription"),
        "tax_rates": StringJSONDatabaseField(name="tax_rates"),
        "test_clock": StringDatabaseField(name="test_clock"),
        "unit_amount": IntegerDatabaseField(name="unit_amount"),
        "unit_amount_decimal": StringDatabaseField(name="unit_amount_decimal"),
    },
    "stripe_payout": {
        "id": StringDatabaseField(name="id"),
        "object": StringDatabaseField(name="object"),
        "amount": IntegerDatabaseField(name="amount"),
        "__arrival_date": IntegerDatabaseField(name="arrival_date", hidden=True),
        "arrival_date": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__arrival_date"])],
                    )
                ],
            ),
            name="arrival_date",
        ),
        "automatic": BooleanDatabaseField(name="automatic"),
        "balance_transaction_id": StringDatabaseField(name="balance_transaction"),
        "__created": IntegerDatabaseField(name="created", hidden=True),
        "created_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__created"])],
                    )
                ],
            ),
            name="created_at",
        ),
        "currency": StringDatabaseField(name="currency"),
        "description": StringDatabaseField(name="description"),
        "destination": StringDatabaseField(name="destination"),
        "failure_balance_transaction": StringDatabaseField(name="failure_balance_transaction"),
        "failure_code": StringDatabaseField(name="failure_code"),
        "failure_message": StringDatabaseField(name="failure_message"),
        "livemode": BooleanDatabaseField(name="livemode"),
        "metadata": StringJSONDatabaseField(name="metadata"),
        "method": StringDatabaseField(name="method"),
        "original_payout": StringDatabaseField(name="original_payout"),
        "reconciliation_status": StringDatabaseField(name="reconciliation_status"),
        "reversed_by": StringDatabaseField(name="reversed_by"),
        "source_type": StringDatabaseField(name="source_type"),
        "statement_descriptor": StringDatabaseField(name="statement_descriptor"),
        "status": StringDatabaseField(name="status"),
        "type": StringDatabaseField(name="type"),
    },
    "stripe_refund": {
        "id": StringDatabaseField(name="id"),
        "object": StringDatabaseField(name="object"),
        "amount": IntegerDatabaseField(name="amount"),
        "balance_transaction_id": StringDatabaseField(name="balance_transaction"),
        "charge_id": StringDatabaseField(name="charge"),
        "__created": IntegerDatabaseField(name="created", hidden=True),
        "created_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__created"])],
                    )
                ],
            ),
            name="created_at",
        ),
        "currency": StringDatabaseField(name="currency"),
        "description": StringDatabaseField(name="description"),
        "destination_details": StringJSONDatabaseField(name="destination_details"),
        "failure_balance_transaction": StringDatabaseField(name="failure_balance_transaction"),
        "failure_reason": StringDatabaseField(name="failure_reason"),
        "instructions_email": StringDatabaseField(name="instructions_email"),
        "metadata": StringJSONDatabaseField(name="metadata"),
        "next_action": StringJSONDatabaseField(name="next_action"),
        "payment_intent_id": StringDatabaseField(name="payment_intent"),
        "reason": StringDatabaseField(name="reason"),
        "receipt_number": StringDatabaseField(name="receipt_number"),
        "source_transfer_reversal": StringDatabaseField(name="source_transfer_reversal"),
        "status": StringDatabaseField(name="status"),
        "transfer_reversal": StringDatabaseField(name="transfer_reversal"),
    },
    "stripe_customerbalancetransaction": {
        "amount": IntegerDatabaseField(name="amount"),
        "checkout_session_id": StringDatabaseField(name="checkout_session"),
        "__created": IntegerDatabaseField(name="created", hidden=True),
        "created_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__created"])],
                    )
                ],
            ),
            name="created_at",
        ),
        "credit_note": StringDatabaseField(name="credit_note"),
        "currency": StringDatabaseField(name="currency"),
        "description": StringDatabaseField(name="description"),
        "ending_balance": IntegerDatabaseField(name="ending_balance"),
        "id": StringDatabaseField(name="id"),
        "customer_id": StringDatabaseField(name="customer"),
        "invoice_id": StringDatabaseField(name="invoice"),
        "livemode": BooleanDatabaseField(name="livemode"),
        "metadata": StringJSONDatabaseField(name="metadata"),
        "object": StringDatabaseField(name="object"),
        "type": StringDatabaseField(name="type"),
    },
    "stripe_customerpaymentmethod": {
        "id": StringDatabaseField(name="id"),
        "object": StringDatabaseField(name="object"),
        "__created": IntegerDatabaseField(name="created", hidden=True),
        "created_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Call(
                        name="toString",
                        args=[ast.Field(chain=["__created"])],
                    )
                ],
            ),
            name="created_at",
        ),
        "billing_details": StringJSONDatabaseField(name="billing_details"),
        "card": StringJSONDatabaseField(name="card"),
        "customer_id": StringDatabaseField(name="customer"),
        "livemode": BooleanDatabaseField(name="livemode"),
        "redaction": StringJSONDatabaseField(name="redaction"),
        "metadata": StringJSONDatabaseField(name="metadata"),
        "type": StringDatabaseField(name="type"),
    },
    "zendesk_brands": {
        "id": IntegerDatabaseField(name="id"),
        "url": StringDatabaseField(name="url"),
        "name": StringDatabaseField(name="name"),
        "active": BooleanDatabaseField(name="active"),
        "default": BooleanDatabaseField(name="default"),
        "brand_url": StringDatabaseField(name="brand_url"),
        "subdomain": StringDatabaseField(name="subdomain"),
        "__created_at": StringDatabaseField(name="created_at", hidden=True),
        "created_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Field(chain=["__created_at"]),
                ],
            ),
            name="created_at",
        ),
        "__updated_at": StringDatabaseField(name="updated_at", hidden=True),
        "updated_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Field(chain=["__updated_at"]),
                ],
            ),
            name="updated_at",
        ),
        "is_deleted": BooleanDatabaseField(name="is_deleted"),
        "has_help_center": BooleanDatabaseField(name="has_help_center"),
        "ticket_form_ids": StringJSONDatabaseField(name="ticket_form_ids"),
        "help_center_state": StringDatabaseField(name="help_center_state"),
        "signature_template": StringDatabaseField(name="signature_template"),
    },
    "zendesk_groups": {
        "id": IntegerDatabaseField(name="id"),
        "url": StringDatabaseField(name="url"),
        "name": StringDatabaseField(name="name"),
        "default": BooleanDatabaseField(name="default"),
        "is_deleted": BooleanDatabaseField(name="deleted"),
        "is_public": BooleanDatabaseField(name="is_public"),
        "__created_at": StringDatabaseField(name="created_at", hidden=True),
        "created_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Field(chain=["__created_at"]),
                ],
            ),
            name="created_at",
        ),
        "__updated_at": StringDatabaseField(name="updated_at", hidden=True),
        "updated_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Field(chain=["__updated_at"]),
                ],
            ),
            name="updated_at",
        ),
        "description": StringDatabaseField(name="description"),
    },
    "zendesk_organizations": {
        "id": IntegerDatabaseField(name="id"),
        "url": StringDatabaseField(name="url"),
        "name": StringDatabaseField(name="name"),
        "tags": StringJSONDatabaseField(name="tags"),
        "notes": StringDatabaseField(name="notes"),
        "details": StringDatabaseField(name="details"),
        "__created_at": StringDatabaseField(name="created_at", hidden=True),
        "created_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Field(chain=["__created_at"]),
                ],
            ),
            name="created_at",
        ),
        "__updated_at": StringDatabaseField(name="updated_at", hidden=True),
        "updated_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Field(chain=["__updated_at"]),
                ],
            ),
            name="updated_at",
        ),
        "external_id": StringDatabaseField(name="external_id"),
        "domain_names": StringJSONDatabaseField(name="domain_names"),
        "shared_tickets": BooleanDatabaseField(name="shared_tickets"),
        "shared_comments": BooleanDatabaseField(name="shared_comments"),
        "organization_fields": StringJSONDatabaseField(name="organization_fields"),
    },
    "zendesk_sla_policies": {
        "id": IntegerDatabaseField(name="id"),
        "url": StringDatabaseField(name="url"),
        "title": StringDatabaseField(name="title"),
        "filter": StringJSONDatabaseField(name="filter"),
        "position": IntegerDatabaseField(name="position"),
        "__created_at": StringDatabaseField(name="created_at", hidden=True),
        "created_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Field(chain=["__created_at"]),
                ],
            ),
            name="created_at",
        ),
        "__updated_at": StringDatabaseField(name="updated_at", hidden=True),
        "updated_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Field(chain=["__updated_at"]),
                ],
            ),
            name="updated_at",
        ),
        "policy_metrics": StringJSONDatabaseField(name="policy_metrics"),
    },
    "zendesk_ticket_events": {
        "id": IntegerDatabaseField(name="id"),
        "via": StringDatabaseField(name="via"),
        "system": StringJSONDatabaseField(name="system"),
        "ticket_id": IntegerDatabaseField(name="ticket_id"),
        "timestamp": IntegerDatabaseField(name="timestamp"),
        "__created_at": StringDatabaseField(name="created_at", hidden=True),
        "created_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Field(chain=["__created_at"]),
                ],
            ),
            name="created_at",
        ),
        "event_type": StringDatabaseField(name="event_type"),
        "updater_id": IntegerDatabaseField(name="updater_id"),
        "child_events": StringJSONDatabaseField(name="child_events"),
        "merged_ticket_ids": StringJSONDatabaseField(name="merged_ticket_ids"),
    },
    "zendesk_ticket_fields": {
        "id": IntegerDatabaseField(name="id"),
        "url": StringDatabaseField(name="url"),
        "type": StringDatabaseField(name="type"),
        "title": StringDatabaseField(name="title"),
        "active": BooleanDatabaseField(name="active"),
        "position": IntegerDatabaseField(name="position"),
        "required": BooleanDatabaseField(name="required"),
        "raw_title": StringDatabaseField(name="raw_title"),
        "removable": BooleanDatabaseField(name="removable"),
        "__created_at": StringDatabaseField(name="created_at", hidden=True),
        "created_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Field(chain=["__created_at"]),
                ],
            ),
            name="created_at",
        ),
        "__updated_at": StringDatabaseField(name="updated_at", hidden=True),
        "updated_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Field(chain=["__updated_at"]),
                ],
            ),
            name="updated_at",
        ),
        "description": StringDatabaseField(name="description"),
        "sub_type_id": IntegerDatabaseField(name="sub_type_id"),
        "custom_statuses": StringJSONDatabaseField(name="custom_statuses"),
        "raw_description": StringDatabaseField(name="raw_description"),
        "title_in_portal": StringDatabaseField(name="title_in_portal"),
        "agent_description": StringDatabaseField(name="agent_description"),
        "visible_in_portal": BooleanDatabaseField(name="visible_in_portal"),
        "editable_in_portal": BooleanDatabaseField(name="editable_in_portal"),
        "required_in_portal": BooleanDatabaseField(name="required_in_portal"),
        "raw_title_in_portal": StringDatabaseField(name="raw_title_in_portal"),
        "collapsed_for_agents": BooleanDatabaseField(name="collapsed_for_agents"),
        "custom_field_options": StringJSONDatabaseField(name="custom_field_options"),
        "system_field_options": StringJSONDatabaseField(name="system_field_options"),
    },
    "zendesk_ticket_metric_events": {
        "id": IntegerDatabaseField(name="id"),
        "__time": StringDatabaseField(name="time", hidden=True),
        "time": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Field(chain=["__time"]),
                ],
            ),
            name="time",
        ),
        "type": StringDatabaseField(name="type"),
        "metric": StringDatabaseField(name="metric"),
        "status": StringJSONDatabaseField(name="status"),
        "ticket_id": IntegerDatabaseField(name="ticket_id"),
        "instance_id": IntegerDatabaseField(name="instance_id"),
    },
    "zendesk_tickets": {
        "id": IntegerDatabaseField(name="id"),
        "url": StringDatabaseField(name="url"),
        "via": StringJSONDatabaseField(name="via"),
        "tags": StringJSONDatabaseField(name="tags"),
        "type": StringDatabaseField(name="type"),
        "fields": StringJSONDatabaseField(name="fields"),
        "status": StringDatabaseField(name="status"),
        "subject": StringDatabaseField(name="subject"),
        "brand_id": IntegerDatabaseField(name="brand_id"),
        "group_id": IntegerDatabaseField(name="group_id"),
        "priority": StringDatabaseField(name="priority"),
        "is_public": BooleanDatabaseField(name="is_public"),
        "recipient": StringDatabaseField(name="recipient"),
        "__created_at": StringDatabaseField(name="created_at", hidden=True),
        "created_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Field(chain=["__created_at"]),
                ],
            ),
            name="created_at",
        ),
        "__updated_at": StringDatabaseField(name="updated_at", hidden=True),
        "updated_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Field(chain=["__updated_at"]),
                ],
            ),
            name="updated_at",
        ),
        "assignee_id": IntegerDatabaseField(name="assignee_id"),
        "description": StringDatabaseField(name="description"),
        "external_id": StringDatabaseField(name="external_id"),
        "raw_subject": StringDatabaseField(name="raw_subject"),
        "email_cc_ids": StringJSONDatabaseField(name="email_cc_ids"),
        "follower_ids": StringJSONDatabaseField(name="follower_ids"),
        "followup_ids": StringJSONDatabaseField(name="followup_ids"),
        "requester_id": IntegerDatabaseField(name="requester_id"),
        "submitter_id": IntegerDatabaseField(name="submitter_id"),
        "custom_fields": StringJSONDatabaseField(name="custom_fields"),
        "has_incidents": BooleanDatabaseField(name="has_incidents"),
        "organization_id": IntegerDatabaseField(name="organization_id"),
        "collaborator_ids": StringJSONDatabaseField(name="collaborator_ids"),
        "custom_status_id": IntegerDatabaseField(name="custom_status_id"),
        "allow_attachments": BooleanDatabaseField(name="allow_attachments"),
        "allow_channelback": BooleanDatabaseField(name="allow_channelback"),
        "generated_timestamp": IntegerDatabaseField(name="generated_timestamp"),
        "sharing_agreement_ids": StringJSONDatabaseField(name="sharing_agreement_ids"),
        "from_messaging_channel": BooleanDatabaseField(name="from_messaging_channel"),
    },
    "zendesk_users": {
        "id": IntegerDatabaseField(name="id"),
        "url": StringDatabaseField(name="url"),
        "name": StringDatabaseField(name="name"),
        "role": StringDatabaseField(name="role"),
        "tags": StringJSONDatabaseField(name="tags"),
        "alias": StringDatabaseField(name="alias"),
        "email": StringDatabaseField(name="email"),
        "notes": StringDatabaseField(name="notes"),
        "phone": StringDatabaseField(name="phone"),
        "photo": StringJSONDatabaseField(name="photo"),
        "active": BooleanDatabaseField(name="active"),
        "locale": StringDatabaseField(name="locale"),
        "shared": BooleanDatabaseField(name="shared"),
        "details": StringDatabaseField(name="details"),
        "verified": BooleanDatabaseField(name="verified"),
        "locale_id": IntegerDatabaseField(name="locale_id"),
        "moderator": BooleanDatabaseField(name="moderator"),
        "role_type": IntegerDatabaseField(name="role_type"),
        "signature": StringDatabaseField(name="signature"),
        "suspended": BooleanDatabaseField(name="suspended"),
        "time_zone": StringDatabaseField(name="time_zone"),
        "__created_at": StringDatabaseField(name="created_at", hidden=True),
        "created_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Field(chain=["__created_at"]),
                ],
            ),
            name="created_at",
        ),
        "__updated_at": StringDatabaseField(name="updated_at", hidden=True),
        "updated_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Field(chain=["__updated_at"]),
                ],
            ),
            name="updated_at",
        ),
        "report_csv": BooleanDatabaseField(name="report_csv"),
        "external_id": StringDatabaseField(name="external_id"),
        "user_fields": StringJSONDatabaseField(name="user_fields"),
        "shared_agent": BooleanDatabaseField(name="shared_agent"),
        "__last_login_at": StringDatabaseField(name="last_login_at", hidden=True),
        "last_login_at": ast.ExpressionField(
            isolate_scope=True,
            expr=ast.Call(
                name="toDateTime",
                args=[
                    ast.Field(chain=["__last_login_at"]),
                ],
            ),
            name="last_login_at",
        ),
        "custom_role_id": IntegerDatabaseField(name="custom_role_id"),
        "iana_time_zone": StringDatabaseField(name="iana_time_zone"),
        "organization_id": IntegerDatabaseField(name="organization_id"),
        "default_group_id": IntegerDatabaseField(name="default_group_id"),
        "restricted_agent": BooleanDatabaseField(name="restricted_agent"),
        "ticket_restriction": StringDatabaseField(name="ticket_restriction"),
        "shared_phone_number": BooleanDatabaseField(name="shared_phone_number"),
        "only_private_comments": BooleanDatabaseField(name="only_private_comments"),
    },
}

HOGQL_FIELD_DLT_TYPE_MAP = {
    StringDatabaseField: "text",
    IntegerDatabaseField: "bigint",
    BooleanDatabaseField: "bool",
    DateTimeDatabaseField: "timestamp",
    StringJSONDatabaseField: "json",
    StringArrayDatabaseField: "json",
    FloatDatabaseField: "double",
    DateDatabaseField: "date",
}


def get_dlt_mapping_for_external_table(table):
    return {
        field.name: {
            "name": field.name,
            "data_type": HOGQL_FIELD_DLT_TYPE_MAP[type(field)],
            "nullable": True,
        }
        for _, field in external_tables[table].items()
        if type(field) is not ast.ExpressionField
    }
