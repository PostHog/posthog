from products.billing_alerts.backend.models import BillingAlertEvent


def test_relative_delta_percentage_supports_full_value_range() -> None:
    field = BillingAlertEvent._meta.get_field("relative_delta_percentage")

    assert field.max_digits == 28
    assert field.decimal_places == 6
