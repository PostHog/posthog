from django.apps import AppConfig


class CustomerAnalyticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.customer_analytics.backend"
    label = "customer_analytics"

    def ready(self) -> None:
        # The receivers must connect in every process because account views can change outside web requests.
        from products.customer_analytics.backend import activity_logging, signals  # noqa: F401, PLC0415

        self._register_person_property_hooks()
        self._register_account_property_hooks()
        self._register_workflows_account_audience()
        self._register_tag_visibility()

    def _register_tag_visibility(self) -> None:
        """Make tag usage counts follow the rules this product's lists apply: a customer task is hidden
        when its account is, and an account note is visible through its account."""
        from posthog.models.tag_visibility import register_tag_visibility_filter, register_tag_visibility_grant

        def _customer_tasks(team_id: int, user_id: int, user_access_control):
            from products.customer_analytics.backend.logic.customer_tasks import (  # noqa: PLC0415
                filter_customer_tasks_on_visible_accounts,
            )

            return filter_customer_tasks_on_visible_accounts(team_id, user_access_control)

        def _account_notes(team_id: int, user_id: int, user_access_control):
            from products.customer_analytics.backend.facade.api import (  # noqa: PLC0415
                _filter_account_note_links_on_visible_accounts,
            )

            return _filter_account_note_links_on_visible_accounts(team_id, user_access_control)

        register_tag_visibility_filter("customer_analytics.CustomerTask", _customer_tasks)
        register_tag_visibility_grant("notebooks.Notebook", _account_notes, object_id_field="notebook_id")

    def _register_workflows_account_audience(self) -> None:
        """Give the workflows batch trigger its account-audience implementation without
        workflows importing this product (the dependency runs the other way). The query
        impls are imported lazily so HogQL stays off the django.setup() path.
        """
        from products.workflows.backend.facade.account_audience import register_account_audience_provider
        from products.workflows.backend.facade.contracts import AccountAudienceFilters

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
            PersonPropertySyncProgress,
            PersonPropertySyncRunRecord,
            PersonPropertySyncSource,
            register_person_property_projection,
            register_person_property_sync_progress_recorder,
            register_person_property_sync_recorder,
            register_person_property_sync_sources,
            register_saved_query_property_sources,
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

        def _saved_query_sources_resolver(team_id: int, saved_query_ids) -> set[str]:
            from products.customer_analytics.backend.logic.person_property_projection import (  # noqa: PLC0415
                saved_queries_with_property_sources,
            )

            return saved_queries_with_property_sources(team_id, saved_query_ids)

        def _progress_recorder(progress: PersonPropertySyncProgress) -> None:
            from products.customer_analytics.backend.logic.person_property_runs import (  # noqa: PLC0415
                record_sync_progress,
            )

            record_sync_progress(progress)

        register_person_property_projection(_projection_resolver)
        register_person_property_sync_sources(_sync_sources_resolver)
        register_person_property_sync_recorder(_run_recorder)
        register_saved_query_property_sources(_saved_query_sources_resolver)
        register_person_property_sync_progress_recorder(_progress_recorder)
