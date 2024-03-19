from typing import Dict
from posthog.hogql import ast
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
)


external_tables: Dict[str, Dict[str, FieldOrTable]] = {
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
            expr=ast.Call(name="fromUnixTimestamp", args=[ast.Field(chain=["__created"])]), name="created_at"
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
        "__dlt_id": StringDatabaseField(name="_dlt_id", hidden=True),
        "__dlt_load_id": StringDatabaseField(name="_dlt_load_id", hidden=True),
    }
}
