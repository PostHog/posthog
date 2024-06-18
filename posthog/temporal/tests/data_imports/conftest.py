import json
import pytest


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
