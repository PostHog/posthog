from infi.clickhouse_orm import migrations

operations = [
    migrations.RunSQL(
        """
    CREATE TABLE cohortpeople
    (
        person_id UUID,
        cohort_id Int64,
        team_id Int64,
        sign Int8
    ) ENGINE = CollapsingMergeTree(sign)
    Order By (team_id, cohort_id, person_id)
    """
    ),
]
