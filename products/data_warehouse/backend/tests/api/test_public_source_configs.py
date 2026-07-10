from posthog.test.base import APIBaseTest

from rest_framework import status


class TestPublicSourceConfigs(APIBaseTest):
    def test_list_returns_source_configs(self):
        response = self.client.get("/api/public_source_configs/")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert isinstance(data, dict)
        assert len(data) > 0

        first_config = next(iter(data.values()))
        assert "name" in first_config
        assert "label" in first_config
        assert "iconPath" in first_config
        assert "fields" in first_config

    def test_matches_wizard_response(self):
        """Public endpoint should return the same data as the authenticated /wizard endpoint."""
        response = self.client.get("/api/public_source_configs/")
        assert response.status_code == status.HTTP_200_OK

        wizard_response = self.client.get("/api/environments/@current/external_data_sources/wizard/")
        assert wizard_response.status_code == status.HTTP_200_OK

        assert response.json() == wizard_response.json()

    def test_accessible_without_authentication(self):
        self.client.logout()
        response = self.client.get("/api/public_source_configs/")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert isinstance(data, dict)
        assert len(data) > 0

    def test_every_config_has_tables_array(self):
        response = self.client.get("/api/public_source_configs/")
        data = response.json()

        for source_type, config in data.items():
            assert "tables" in config, f"{source_type} missing tables"
            assert isinstance(config["tables"], list), f"{source_type} tables is not a list"

    def test_fixed_schema_source_lists_tables(self):
        """Fixed-schema API sources (e.g. Stripe) expose their documented table catalog."""
        response = self.client.get("/api/public_source_configs/")
        stripe = response.json()["Stripe"]

        tables = stripe["tables"]
        assert len(tables) > 0
        names = {t["name"] for t in tables}
        assert "Customer" in names

        for table in tables:
            assert set(table.keys()) >= {
                "name",
                "label",
                "description",
                "sync_methods",
                "incremental_fields",
                "primary_keys",
            }
            assert isinstance(table["sync_methods"], list)
            assert len(table["sync_methods"]) > 0

    def test_sql_source_returns_no_tables(self):
        """SQL sources have user-defined schemas, so the catalog is empty (renders a generic note)."""
        response = self.client.get("/api/public_source_configs/")
        assert response.json()["Postgres"]["tables"] == []

    def test_every_config_exposes_version_fields(self):
        """The external version-update automation consumes these exact field names."""
        response = self.client.get("/api/public_source_configs/")
        data = response.json()

        for source_type, config in data.items():
            assert isinstance(config["versions"], list) and len(config["versions"]) > 0, source_type
            assert config["defaultVersion"] in config["versions"], source_type
            assert config["apiDocsUrl"] is None or config["apiDocsUrl"].startswith("https://"), source_type
            assert isinstance(config["deprecatedVersions"], list), source_type

        stripe = data["Stripe"]
        assert stripe["versions"] == ["2024-09-30.acacia"]
        assert stripe["defaultVersion"] == "2024-09-30.acacia"
        assert stripe["apiDocsUrl"] == "https://docs.stripe.com/changelog"

    def test_many_fixed_schema_sources_list_tables(self):
        """Guard the opt-in mechanism: a large share of sources expose a static table catalog.

        ~140 sources set `lists_tables_without_credentials`; if the mechanism regresses this
        collapses toward zero. The loose threshold tolerates sources being added or removed.
        """
        response = self.client.get("/api/public_source_configs/")
        with_tables = [name for name, config in response.json().items() if config["tables"]]
        assert len(with_tables) >= 100, f"only {len(with_tables)} sources list tables"
