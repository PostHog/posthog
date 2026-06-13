from django.apps import AppConfig


class CohortsConfig(AppConfig):
    # AutoField (INT4) matches the legacy posthog app default so existing
    # posthog_cohort / posthog_cohortpeople id columns stay compatible with the
    # Rust flags/cohorts services which decode id as i32.
    default_auto_field = "django.db.models.AutoField"
    name = "products.cohorts.backend"
    label = "cohorts"
