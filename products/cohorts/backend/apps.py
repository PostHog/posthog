from django.apps import AppConfig


class CohortsConfig(AppConfig):
    # AutoField (INT4) matches the legacy posthog app default so existing
    # posthog_cohort / posthog_cohortpeople id columns stay compatible with the
    # Rust flags/cohorts services which decode id as i32.
    default_auto_field = "django.db.models.AutoField"
    name = "products.cohorts.backend"
    label = "cohorts"

    def ready(self) -> None:
        # Registers the cohort resolver for entity dependency reads. Kept in its own light
        # module so django.setup() does not pull the API module in.
        from products.cohorts.backend import entity_dependencies  # noqa: F401, PLC0415
