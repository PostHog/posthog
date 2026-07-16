from django.apps import AppConfig


class CustomerAnalyticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.customer_analytics.backend"
    label = "customer_analytics"

    def ready(self) -> None:
        self._register_person_property_hooks()

    def _register_person_property_hooks(self) -> None:
        """Tell the data-import pipeline which columns to stage for a schema's person-property
        sources, and give its post-sync upsert job the full source configs — without
        warehouse_sources importing this product. The impls are imported lazily so the models stay
        off the django.setup() path.
        """
        from products.warehouse_sources.backend.facade.hooks import (
            PersonPropertySourceProjection,
            PersonPropertySyncSource,
            register_person_property_projection,
            register_person_property_sync_sources,
        )

        def _projection_resolver(team_id: int, schema_id) -> list[PersonPropertySourceProjection] | None:
            from products.customer_analytics.backend.logic.person_property_projection import (  # noqa: PLC0415
                person_property_projection,
            )

            return person_property_projection(team_id, schema_id)

        def _sync_sources_resolver(team_id: int, schema_id) -> list[PersonPropertySyncSource] | None:
            from products.customer_analytics.backend.logic.person_property_projection import (  # noqa: PLC0415
                person_property_sync_sources,
            )

            return person_property_sync_sources(team_id, schema_id)

        register_person_property_projection(_projection_resolver)
        register_person_property_sync_sources(_sync_sources_resolver)
