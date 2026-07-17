# Django-free home for the exchange-rate ClickHouse dictionary constants. Kept out of
# posthog.models.exchange_rate.sql (whose package __init__ boots the Django ORM) so the HogQL
# engine — schema tables and the printer — can reference them without booting Django.
# posthog.models.exchange_rate.sql re-exports these for existing callers.

EXCHANGE_RATE_TABLE_NAME = "exchange_rate"
EXCHANGE_RATE_DICTIONARY_NAME = "exchange_rate_dict"

# Storing 10 decimal places is more than enough
# Ideally we should have gone with 4 because that's all we need for most currencies
# but Bitcoin messes this up because it's so valuable compared to the Dollar (our base currency)
#
# If Bitcoin ever moons it even further, we can increase this to 12 or 14
# but for now 10 is more than enough
EXCHANGE_RATE_DECIMAL_PRECISION = 10
