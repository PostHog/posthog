"""Public data contracts for the async_migrations product.

The async_migrations facade is behavioral: it exposes capability functions over the
ClickHouse async-migration engine, which operate on the core ``AsyncMigration`` Django
model (``posthog.models.async_migration``) and primitive values. The product owns no
data model of its own, so there are no product-owned contracts to define here — the
file exists to mark the product as isolated (strict structural lint) and is the home
for any future cross-boundary data record.
"""
