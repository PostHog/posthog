from django.apps import AppConfig


class AlertsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.alerts.backend"
    label = "alerts"

    def ready(self) -> None:
        # Connect the alert activity-log and cleanup receivers (hog-function teardown,
        # subscription delete logging) at app-population. They used to wire in via the viewset
        # import; the lazy API router no longer pulls that, so connect here. They live in their
        # own module because the API module imports the alert detector stack (numpy) at module
        # scope — see activity_logging's docstring.
        from products.alerts.backend import activity_logging  # noqa: F401, PLC0415

        # The platform cannot import this product, so it reaches this product's destinations, the schema
        # an edit to an insight alert's copy is checked against, and the `$insight_alert_firing` events and
        # native wording of an insight alert, here.
        from products.alerts.backend.facade.destinations import (  # noqa: PLC0415
            choose_delivery_path,
            list_delivery_destination_groups,
        )
        from products.alerts.backend.platform_alert_wording import describe_insight_transition  # noqa: PLC0415
        from products.alerts.backend.platform_hooks import (  # noqa: PLC0415
            emit_insight_legacy_events,
            insight_chart_image,
            render_insight_slack_message,
        )
        from products.alerts.backend.platform_source_config import load_insight_source_config  # noqa: PLC0415
        from products.alerts_platform.backend.facade.contracts import SourceKind  # noqa: PLC0415
        from products.alerts_platform.backend.facade.delivery import (  # noqa: PLC0415
            register_delivery_path_chooser,
            register_destination_resolver,
            register_image_resolver,
            register_legacy_event_emitter,
            register_source_describer,
            register_source_slack_renderer,
        )
        from products.alerts_platform.backend.facade.source_configs import register_source_config  # noqa: PLC0415

        register_destination_resolver(list_delivery_destination_groups)
        register_delivery_path_chooser(choose_delivery_path)
        register_legacy_event_emitter(SourceKind.INSIGHT, emit_insight_legacy_events)
        register_source_describer(SourceKind.INSIGHT, describe_insight_transition)
        register_image_resolver(SourceKind.INSIGHT, insight_chart_image)
        register_source_slack_renderer(SourceKind.INSIGHT, render_insight_slack_message)
        register_source_config(SourceKind.INSIGHT, load_insight_source_config)
