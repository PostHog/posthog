# manually created by andrewjmcgehee

from django.db import migrations

DROP_TRIGGER_DETECT_DAG_MISMATCH_ON_INSERT = """\
DROP TRIGGER IF EXISTS posthog_datamodelingedge_detect_dag_mismatch_on_insert ON posthog_datamodelingedge;
"""

DROP_TRIGGER_DETECT_DAG_MISMATCH_ON_UPDATE = """\
DROP TRIGGER IF EXISTS posthog_datamodelingedge_detect_dag_mismatch_on_update ON posthog_datamodelingedge;
"""

# workaround for create if not exists is to drop if exists and then create

CREATE_TRIGGER_DETECT_DAG_MISMATCH_ON_INSERT = f"""\
{DROP_TRIGGER_DETECT_DAG_MISMATCH_ON_INSERT}
CREATE TRIGGER posthog_datamodelingedge_detect_dag_mismatch_on_insert
BEFORE INSERT ON posthog_datamodelingedge
FOR EACH ROW
EXECUTE FUNCTION posthog_datamodelingedge_detect_dag_mismatch();
"""

CREATE_TRIGGER_DETECT_DAG_MISMATCH_ON_UPDATE = f"""\
{DROP_TRIGGER_DETECT_DAG_MISMATCH_ON_UPDATE}
CREATE TRIGGER posthog_datamodelingedge_detect_dag_mismatch_on_update
BEFORE UPDATE OF team_id, dag_id, source_id, target_id ON posthog_datamodelingedge
FOR EACH ROW
WHEN (
    OLD.team_id IS DISTINCT FROM NEW.team_id OR
    OLD.dag_id IS DISTINCT FROM NEW.dag_id OR
    OLD.source_id IS DISTINCT FROM NEW.source_id OR
    OLD.target_id IS DISTINCT FROM NEW.target_id
)
EXECUTE FUNCTION posthog_datamodelingedge_detect_dag_mismatch();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0005_create_detect_dag_mismatch_function"),
    ]

    operations = [
        migrations.RunSQL(CREATE_TRIGGER_DETECT_DAG_MISMATCH_ON_INSERT, DROP_TRIGGER_DETECT_DAG_MISMATCH_ON_INSERT),
        migrations.RunSQL(CREATE_TRIGGER_DETECT_DAG_MISMATCH_ON_UPDATE, DROP_TRIGGER_DETECT_DAG_MISMATCH_ON_UPDATE),
    ]
