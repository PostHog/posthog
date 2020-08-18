from django_clickhouse import migrations

from ee.clickhouse.models import ClickHouseEvent


class Migration(migrations.Migration):
    operations = [
        migrations.CreateTable(ClickHouseEvent),
    ]
