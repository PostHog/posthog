from infi.clickhouse_orm import migrations  # type: ignore

from ee.clickhouse.sql.person import PERSONS_UP_TO_DATE_MATERIALIZED_VIEW, PERSONS_UP_TO_DATE_VIEW

operations = [migrations.RunSQL(PERSONS_UP_TO_DATE_MATERIALIZED_VIEW), migrations.RunSQL(PERSONS_UP_TO_DATE_VIEW)]
