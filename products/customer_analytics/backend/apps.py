from django.apps import AppConfig


class CustomerAnalyticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.customer_analytics.backend"
    label = "customer_analytics"

    def ready(self) -> None:
        self._register_person_property_projection()

    def _register_person_property_projection(self) -> None:
        """Tell the data-import pipeline which columns to stage for a schema's person-property
        sources, without warehouse_sources importing this product. The impl is imported lazily so
        the models stay off the django.setup() path.
        """
        from products.warehouse_sources.backend.facade.hooks import register_person_property_projection

        def _resolver(team_id: int, schema_id) -> list[str] | None:
            from products.customer_analytics.backend.logic.person_property_projection import (  # noqa: PLC0415
                person_property_projection_columns,
            )

            return person_property_projection_columns(team_id, schema_id)

        register_person_property_projection(_resolver)
