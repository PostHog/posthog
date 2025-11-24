import pytest
from unittest import mock

from posthog.models.hog_functions.hog_function import HogFunction
from posthog.temporal.data_imports.pipelines.pipeline.cdp_producer import CDPProducer

from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.models.table import DataWarehouseTable
from products.data_warehouse.backend.types import ExternalDataSourceType


@pytest.mark.django_db(transaction=True)
def test_should_produce_table_no_hog_function(team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    table = DataWarehouseTable.objects.create(team=team, name="postgres_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.MagicMock())
    assert producer.should_produce_table is False


@pytest.mark.django_db(transaction=True)
def test_should_produce_table_with_matching_hog_function(team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    table = DataWarehouseTable.objects.create(team=team, name="postgres_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    HogFunction.objects.create(
        team=team,
        enabled=True,
        filters={"source": "data-warehouse", "data_warehouse": [{"table_name": "postgres.table_1"}]},
    )

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.MagicMock())
    assert producer.should_produce_table is True


@pytest.mark.django_db(transaction=True)
def test_should_produce_table_with_disabled_matching_hog_function(team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    table = DataWarehouseTable.objects.create(team=team, name="postgres_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    HogFunction.objects.create(
        team=team,
        enabled=False,
        filters={"source": "data-warehouse", "data_warehouse": [{"table_name": "postgres.table_1"}]},
    )

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.MagicMock())
    assert producer.should_produce_table is False


@pytest.mark.django_db(transaction=True)
def test_should_produce_table_with_new_style_table_name(team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
    table = DataWarehouseTable.objects.create(team=team, name="postgres.table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    HogFunction.objects.create(
        team=team,
        enabled=True,
        filters={"source": "data-warehouse", "data_warehouse": [{"table_name": "postgres.table_1"}]},
    )

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.MagicMock())
    assert producer.should_produce_table is True


@pytest.mark.django_db(transaction=True)
def test_should_produce_table_with_source_prefix(team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES, prefix="eu")
    table = DataWarehouseTable.objects.create(team=team, name="postgres_eu_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    HogFunction.objects.create(
        team=team,
        enabled=True,
        filters={"source": "data-warehouse", "data_warehouse": [{"table_name": "postgres.eu.table_1"}]},
    )

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.MagicMock())
    assert producer.should_produce_table is True


@pytest.mark.django_db(transaction=True)
def test_should_produce_table_with_leading_underscore_source_prefix(team):
    source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES, prefix="_eu")
    table = DataWarehouseTable.objects.create(team=team, name="postgres_eu_table_1", external_data_source=source)
    schema = ExternalDataSchema.objects.create(team=team, name="table_1", source=source, table=table)

    HogFunction.objects.create(
        team=team,
        enabled=True,
        filters={"source": "data-warehouse", "data_warehouse": [{"table_name": "postgres.eu.table_1"}]},
    )

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.MagicMock())
    assert producer.should_produce_table is True
