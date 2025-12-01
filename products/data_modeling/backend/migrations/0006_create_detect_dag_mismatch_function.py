# manually created by andrewjmcgehee

from django.db import migrations

CREATE_OR_REPLACE_DETECT_DAG_MISMATCH = """\
CREATE OR REPLACE FUNCTION posthog_datamodelingedge_detect_dag_mismatch()
RETURNS TRIGGER AS $$
DECLARE
    source_team_id BIGINT;
    source_dag_id TEXT;
    target_team_id BIGINT;
    target_dag_id TEXT;
BEGIN
    SELECT team_id, dag_id INTO source_team_id, source_dag_id FROM posthog_datamodelingnode WHERE id = NEW.source_id;
    SELECT team_id, dag_id INTO target_team_id, target_dag_id FROM posthog_datamodelingnode WHERE id = NEW.target_id;

    IF source_team_id != NEW.team_id OR target_team_id != NEW.team_id THEN
        RAISE EXCEPTION 'Edge team_id (%) does not match source node team_id (%) or target node team_id (%)',
            NEW.team_id, source_team_id, target_team_id;
    END IF;

    IF source_dag_id != NEW.dag_id OR target_dag_id != NEW.dag_id THEN
        RAISE EXCEPTION 'Edge dag_id (%) does not match source node dag_id (%) or target node dag_id (%)',
            NEW.dag_id, source_dag_id, target_dag_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


DROP_DETECT_DAG_MISMATCH = """\
DROP FUNCTION IF EXISTS posthog_datamodelingedge_detect_dag_mismatch();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0004_create_detect_cycles_triggers"),
    ]

    operations = [
        migrations.RunSQL(CREATE_OR_REPLACE_DETECT_DAG_MISMATCH, DROP_DETECT_DAG_MISMATCH),
    ]
