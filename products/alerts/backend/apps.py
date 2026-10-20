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

        # The platform cannot import this product, so it reaches this product's destinations, and
        # the `$insight_alert_firing` events and native wording of an insight alert, here.
        from products.alerts.backend.facade.destinations import (  # noqa: PLC0415
            choose_delivery_path,
            list_delivery_destination_groups,
        )
        from products.alerts.backend.platform_alert_legacy_events import emit_insight_legacy_events  # noqa: PLC0415
        from products.alerts.backend.platform_alert_wording import describe_insight_transition  # noqa: PLC0415
        from products.alerts_platform.backend.facade.contracts import SourceKind  # noqa: PLC0415
        from products.alerts_platform.backend.facade.delivery import (  # noqa: PLC0415
            register_delivery_path_chooser,
            register_destination_resolver,
            register_legacy_event_emitter,
            register_source_describer,
        )

        register_destination_resolver(list_delivery_destination_groups)
        register_delivery_path_chooser(choose_delivery_path)
        register_legacy_event_emitter(SourceKind.INSIGHT, emit_insight_legacy_events)
        register_source_describer(SourceKind.INSIGHT, describe_insight_transition)
