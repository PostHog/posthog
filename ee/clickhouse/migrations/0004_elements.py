from django_clickhouse import migrations

from ee.clickhouse.sql.elements import ELEMENT_GROUP_TABLE_SQL, ELEMENTS_TABLE_SQL

operations = [migrations.RunSQL(ELEMENTS_TABLE_SQL), migrations.RunSQL(ELEMENT_GROUP_TABLE_SQL)]
