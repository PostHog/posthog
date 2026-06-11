from unittest.mock import MagicMock, patch

from posthog.temporal.data_imports.sources.postgres.cdc.adapter import PostgresCDCAdapter

_ADAPTER = "posthog.temporal.data_imports.sources.postgres.cdc.adapter"


def _source(**cdc_overrides):
    job_inputs = {
        "host": "localhost",
        "port": 5432,
        "database": "app",
        "user": "user",
        "password": "pass",
        "schema": "public",
        **cdc_overrides,
    }
    source = MagicMock()
    source.job_inputs = job_inputs
    return source


def _fake_conn():
    cm = MagicMock()
    cm.return_value.__enter__.return_value = object()
    cm.return_value.__exit__.return_value = None
    return cm


class TestSetupResourcesPreflight:
    @patch(f"{_ADAPTER}.drop_slot_and_publication")
    @patch(f"{_ADAPTER}.create_slot_and_publication")
    @patch(f"{_ADAPTER}.publication_exists", return_value=False)
    @patch(f"{_ADAPTER}.slot_exists", return_value=True)
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_posthog_refuses_when_slot_already_exists(
        self, _conn, _slot_exists, _pub_exists, mock_create, mock_drop
    ) -> None:
        fields, error = PostgresCDCAdapter().setup_resources(
            _source(), {"cdc_management_mode": "posthog", "cdc_slot_name": "existing_slot"}
        )
        assert fields == {}
        assert error is not None and "already exists" in error
        # Must not create, and must not roll back (drop) a slot it didn't create.
        mock_create.assert_not_called()
        mock_drop.assert_not_called()

    @patch(f"{_ADAPTER}.drop_slot_and_publication")
    @patch(f"{_ADAPTER}.create_slot_and_publication")
    @patch(f"{_ADAPTER}.publication_exists", return_value=True)
    @patch(f"{_ADAPTER}.slot_exists", return_value=False)
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_posthog_refuses_when_publication_already_exists(
        self, _conn, _slot_exists, _pub_exists, mock_create, mock_drop
    ) -> None:
        fields, error = PostgresCDCAdapter().setup_resources(
            _source(), {"cdc_management_mode": "posthog", "cdc_publication_name": "existing_pub"}
        )
        assert fields == {}
        assert error is not None and "already exists" in error
        mock_create.assert_not_called()
        mock_drop.assert_not_called()

    @patch(f"{_ADAPTER}.drop_slot")
    @patch(f"{_ADAPTER}.create_slot")
    @patch(f"{_ADAPTER}.publication_exists", return_value=True)
    @patch(f"{_ADAPTER}.slot_exists", return_value=True)
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_self_managed_refuses_when_slot_already_exists(
        self, _conn, _slot_exists, _pub_exists, mock_create, mock_drop
    ) -> None:
        fields, error = PostgresCDCAdapter().setup_resources(
            _source(), {"cdc_management_mode": "self_managed", "cdc_slot_name": "existing_slot"}
        )
        assert fields == {}
        assert error is not None and "already exists" in error
        mock_create.assert_not_called()
        mock_drop.assert_not_called()

    @patch(f"{_ADAPTER}.drop_slot_and_publication")
    @patch(f"{_ADAPTER}.create_slot_and_publication", side_effect=RuntimeError("boom"))
    @patch(f"{_ADAPTER}.publication_exists", return_value=False)
    @patch(f"{_ADAPTER}.slot_exists", return_value=False)
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_posthog_rolls_back_only_after_verifying_absence(
        self, _conn, _slot_exists, _pub_exists, _create, mock_drop
    ) -> None:
        # Both verified absent, then create fails → safe to drop what we just made.
        fields, error = PostgresCDCAdapter().setup_resources(
            _source(),
            {"cdc_management_mode": "posthog", "cdc_slot_name": "s", "cdc_publication_name": "p"},
        )
        assert fields == {}
        assert error is not None and "boom" in error
        mock_drop.assert_called_once()
        assert mock_drop.call_args.args[1:] == ("s", "p")


class TestAlterPublicationMembership:
    @patch(f"{_ADAPTER}.add_table_to_publication")
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_add_table_noop_for_self_managed(self, _conn, mock_add) -> None:
        source = _source(cdc_enabled=True, cdc_management_mode="self_managed", cdc_publication_name="pub")
        PostgresCDCAdapter().add_table(source, "public", "orders")
        mock_add.assert_not_called()

    @patch(f"{_ADAPTER}.add_table_to_publication")
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_add_table_for_posthog_managed(self, _conn, mock_add) -> None:
        source = _source(cdc_enabled=True, cdc_management_mode="posthog", cdc_publication_name="pub")
        PostgresCDCAdapter().add_table(source, "public", "orders")
        mock_add.assert_called_once()
        assert mock_add.call_args.args[1:] == ("pub", "public", "orders")

    @patch(f"{_ADAPTER}.remove_table_from_publication")
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_remove_table_for_posthog_managed(self, _conn, mock_remove) -> None:
        source = _source(cdc_enabled=True, cdc_management_mode="posthog", cdc_publication_name="pub")
        PostgresCDCAdapter().remove_table(source, "analytics", "events")
        mock_remove.assert_called_once()
        assert mock_remove.call_args.args[1:] == ("pub", "analytics", "events")

    @patch(f"{_ADAPTER}.add_table_to_publication")
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_add_table_noop_without_publication(self, _conn, mock_add) -> None:
        source = _source(cdc_enabled=True, cdc_management_mode="posthog")
        PostgresCDCAdapter().add_table(source, "public", "orders")
        mock_add.assert_not_called()
