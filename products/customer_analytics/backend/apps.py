from django.apps import AppConfig


class CustomerAnalyticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.customer_analytics.backend"
    label = "customer_analytics"

    def ready(self) -> None:
        self._register_person_property_hooks()
        self._register_account_property_hooks()
        self._register_workflows_account_audience()

    def _register_workflows_account_audience(self) -> None:
        """Give the workflows batch trigger its account-audience implementation without
        workflows importing this product (the dependency runs the other way). The query
        impls are imported lazily so HogQL stays off the django.setup() path.
        """
        from products.workflows.backend.services.account_audience import (
            AccountAudienceFilters,
            register_account_audience_provider,
        )

        class _Provider:
            def count_accounts(self, team, filters: AccountAudienceFilters) -> int:
                from products.customer_analytics.backend.facade import api  # noqa: PLC0415

                return api.count_accounts_for_audience(team, filters)

            def list_account_external_ids(
                self, team, filters: AccountAudienceFilters, *, cursor: str | None, limit: int
            ) -> list[str]:
                from products.customer_analytics.backend.facade import api  # noqa: PLC0415

                return api.list_account_external_ids_for_audience(team, filters, cursor=cursor, limit=limit)

            def get_account_group_type_name(self, team) -> str | None:
                from products.customer_analytics.backend.facade import api  # noqa: PLC0415

                return api.get_account_group_type_name(team)

        register_account_audience_provider(_Provider())

    def _register_account_property_hooks(self) -> None:
        from products.warehouse_sources.backend.facade.hooks import (
            AccountPropertySourceProjection,
            WarehouseBinding,
            register_account_property_projection,
        )

        def _projection_resolver(
            team_id: int, binding: WarehouseBinding
        ) -> list[AccountPropertySourceProjection] | None:
            from products.customer_analytics.backend.logic.account_property_projection import (  # noqa: PLC0415
                account_property_projection,
            )

            return account_property_projection(team_id, binding)

        register_account_property_projection(_projection_resolver)

    def _register_person_property_hooks(self) -> None:
        """Tell the data-import pipeline which columns to stage for a schema's person-property
        sources, and give its post-sync upsert job the full source configs — without
        warehouse_sources importing this product. The impls are imported lazily so the models stay
        off the django.setup() path.
        """
        from products.warehouse_sources.backend.facade.hooks import (
            PersonPropertySourceProjection,
            PersonPropertySyncRunRecord,
            PersonPropertySyncSource,
            register_person_property_projection,
            register_person_property_sync_recorder,
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

        def _run_recorder(record: PersonPropertySyncRunRecord) -> None:
            from products.customer_analytics.backend.logic.person_property_runs import record_sync_run  # noqa: PLC0415

            record_sync_run(record)

        register_person_property_projection(_projection_resolver)
        register_person_property_sync_sources(_sync_sources_resolver)
        register_person_property_sync_recorder(_run_recorder)
