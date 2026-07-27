from django.apps import AppConfig


class AIObservabilityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.ai_observability.backend"
    label = "ai_observability"

    def ready(self) -> None:
        # Connect the Evaluation activity-log receiver at app-population. It lives in a light
        # activity_logging module (not the evaluations viewset, which pulls scipy / google.genai /
        # the ai_observability Temporal worker) so wiring it here stays off the django.setup() path.
        from products.ai_observability.backend import activity_logging  # noqa: F401, PLC0415
