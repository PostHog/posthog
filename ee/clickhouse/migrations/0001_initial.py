from django_clickhouse import migrations

from ee.clickhouse.models import ClickHouseActionEvent, ClickHouseEvent, ClickHousePerson, ClickHousePersonDistinctId


class Migration(migrations.Migration):
    operations = [
        migrations.CreateTable(ClickHouseEvent),
        migrations.CreateTable(ClickHousePerson),
        migrations.CreateTable(ClickHousePersonDistinctId),
        migrations.CreateTable(ClickHouseActionEvent),
    ]
