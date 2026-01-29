import pytest

from posthog.ducklake.models import CrossAccountDestination


class TestCrossAccountDestination:
    def test_get_s3_base_path(self):
        dest = CrossAccountDestination(
            role_arn="arn:aws:iam::123456789012:role/MyRole",
            external_id="ext-id-123",
            bucket="my-customer-bucket",
            region="us-west-2",
        )
        assert dest.get_s3_base_path() == "s3://my-customer-bucket/"

    def test_frozen_dataclass(self):
        dest = CrossAccountDestination(
            role_arn="arn:aws:iam::123456789012:role/MyRole",
            external_id="ext-id-123",
            bucket="bucket",
            region="us-east-1",
        )
        with pytest.raises(AttributeError):
            dest.bucket = "new-bucket"


class TestDuckLakeCatalogModel:
    @pytest.mark.django_db
    def test_get_catalog_connection_string(self):
        from posthog.ducklake.models import DuckLakeCatalog
        from posthog.models import Team

        team = Team.objects.create(name="Test Team", organization=None)

        catalog = DuckLakeCatalog(
            team=team,
            rds_host="my-rds.cluster.us-east-1.rds.amazonaws.com",
            rds_port=5432,
            rds_database="ducklake",
            rds_username="admin",
            rds_password="secret123",
            s3_bucket="customer-bucket",
            s3_region="us-east-1",
            cross_account_role_arn="arn:aws:iam::111111111111:role/DucklingAccess",
            cross_account_external_id="ext-abc",
        )

        conn_str = catalog.get_catalog_connection_string()
        assert "dbname=ducklake" in conn_str
        assert "host=my-rds.cluster.us-east-1.rds.amazonaws.com" in conn_str
        assert "port=5432" in conn_str
        assert "user=admin" in conn_str
        assert "password=secret123" in conn_str

    @pytest.mark.django_db
    def test_get_data_path(self):
        from posthog.ducklake.models import DuckLakeCatalog
        from posthog.models import Team

        team = Team.objects.create(name="Test Team", organization=None)

        catalog = DuckLakeCatalog(
            team=team,
            rds_host="localhost",
            rds_username="user",
            rds_password="pass",
            s3_bucket="my-data-bucket",
            cross_account_role_arn="arn:aws:iam::111111111111:role/Role",
            cross_account_external_id="ext",
        )

        assert catalog.get_data_path() == "s3://my-data-bucket/"

    @pytest.mark.django_db
    def test_to_cross_account_destination(self):
        from posthog.ducklake.models import DuckLakeCatalog
        from posthog.models import Team

        team = Team.objects.create(name="Test Team", organization=None)

        catalog = DuckLakeCatalog(
            team=team,
            rds_host="localhost",
            rds_username="user",
            rds_password="pass",
            s3_bucket="customer-bucket",
            s3_region="eu-west-1",
            cross_account_role_arn="arn:aws:iam::222222222222:role/CustomerRole",
            cross_account_external_id="external-id-456",
        )

        dest = catalog.to_cross_account_destination()
        assert dest.role_arn == "arn:aws:iam::222222222222:role/CustomerRole"
        assert dest.external_id == "external-id-456"
        assert dest.bucket == "customer-bucket"
        assert dest.region == "eu-west-1"

    @pytest.mark.django_db
    def test_to_config_dict(self):
        from posthog.ducklake.models import DuckLakeCatalog
        from posthog.models import Team

        team = Team.objects.create(name="Test Team", organization=None)

        catalog = DuckLakeCatalog(
            team=team,
            rds_host="rds.example.com",
            rds_port=5433,
            rds_database="mydb",
            rds_username="dbuser",
            rds_password="dbpass",
            s3_bucket="data-bucket",
            s3_region="ap-southeast-1",
            cross_account_role_arn="arn:aws:iam::111:role/Role",
            cross_account_external_id="ext",
        )

        config = catalog.to_config_dict()
        assert config["DUCKLAKE_RDS_HOST"] == "rds.example.com"
        assert config["DUCKLAKE_RDS_PORT"] == "5433"
        assert config["DUCKLAKE_RDS_DATABASE"] == "mydb"
        assert config["DUCKLAKE_RDS_USERNAME"] == "dbuser"
        assert config["DUCKLAKE_RDS_PASSWORD"] == "dbpass"
        assert config["DUCKLAKE_BUCKET"] == "data-bucket"
        assert config["DUCKLAKE_BUCKET_REGION"] == "ap-southeast-1"


class TestGetTeamCatalog:
    @pytest.mark.django_db
    def test_returns_none_when_not_found(self):
        from posthog.ducklake.models import get_team_catalog

        result = get_team_catalog(999999)
        assert result is None

    @pytest.mark.django_db
    def test_returns_catalog_when_exists(self):
        from posthog.ducklake.models import DuckLakeCatalog, get_team_catalog
        from posthog.models import Team

        team = Team.objects.create(name="Test Team", organization=None)

        DuckLakeCatalog.objects.create(
            team=team,
            rds_host="localhost",
            rds_username="user",
            rds_password="pass",
            s3_bucket="bucket",
            cross_account_role_arn="arn:aws:iam::111:role/Role",
            cross_account_external_id="ext",
        )

        result = get_team_catalog(team.id)
        assert result is not None
        assert result.team_id == team.id
        assert result.s3_bucket == "bucket"
