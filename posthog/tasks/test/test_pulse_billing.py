from posthog.tasks.usage_report import POSTHOG_AI_PRODUCTS, UNBILLED_TASK_ORIGIN_PRODUCTS


def test_pulse_subscription_is_billed_as_posthog_ai() -> None:
    assert "pulse_subscription" in POSTHOG_AI_PRODUCTS
    assert "pulse_subscription" not in UNBILLED_TASK_ORIGIN_PRODUCTS
