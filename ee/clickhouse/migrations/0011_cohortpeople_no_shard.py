from infi.clickhouse_orm import migrations

from ee.clickhouse.sql.cohort import CREATE_COHORTPEOPLE_TABLE_SQL, DROP_COHORTPEOPLE_TABLE_SQL
from posthog.settings import CLICKHOUSE_REPLICATION

# run create table again with proper configuration
operations = [migrations.RunSQL(DROP_COHORTPEOPLE_TABLE_SQL), migrations.RunSQL(CREATE_COHORTPEOPLE_TABLE_SQL)]
