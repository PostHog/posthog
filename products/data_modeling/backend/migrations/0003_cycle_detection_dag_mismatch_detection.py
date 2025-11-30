# manually created by andrewjmcgehee

from django.db import migrations

# detect cycles
CREATE_OR_REPLACE_DETECT_CYCLES = """\
CREATE OR REPLACE FUNCTION detect_cycles()
RETURNS TRIGGER AS $$
BEGIN
  -- trivial case
  IF NEW.source_id = NEW.target_id THEN
    RAISE EXCEPTION 'Self-loop detected: team=% dag=% source=% target=% source is reachable traversing from target',
    NEW.team_id, NEW.dag_id, NEW.source_id, NEW.target_id;
  END IF;

  -- check if adding this edge creates a cycle by testing whether
  -- NEW.source is reachable from NEW.target via existing edges
  IF EXISTS (
    WITH RECURSIVE reachable(node_id) AS (
      -- base case
      SELECT e.target_id
      FROM posthog_datamodelingedge e
      WHERE e.source_id = NEW.target_id
        AND e.team_id = NEW.team_id
        AND e.dag_id = NEW.dag_id

      UNION

      -- recursive case
      SELECT e.target_id
      FROM posthog_datamodelingedge e
      INNER JOIN reachable r ON e.source_id = r.node_id
      WHERE e.target_id <> NEW.target_id
        AND e.team_id = NEW.team_id
        AND e.dag_id = NEW.dag_id
    )
    SELECT 1 FROM reachable WHERE node_id = NEW.source_id
  ) THEN
    RAISE EXCEPTION 'Cycle detected: team=% dag=% source=% target=% source is reachable traversing from target',
      NEW.team_id, NEW.dag_id, NEW.source_id, NEW.target_id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

CREATE_TRIGGER_DETECT_CYCLES_ON_INSERT = """\
CREATE TRIGGER detect_cycles_on_insert
BEFORE INSERT ON posthog_datamodelingedge
FOR EACH ROW
EXECUTE FUNCTION detect_cycles();
"""

CREATE_TRIGGER_DETECT_CYCLES_ON_UPDATE = """\
CREATE TRIGGER detect_cycles_on_update
BEFORE UPDATE OF source_id, target_id ON posthog_datamodelingedge
FOR EACH ROW
WHEN (OLD.source_id IS DISTINCT FROM NEW.source_id OR OLD.target_id IS DISTINCT FROM NEW.target_id)
EXECUTE FUNCTION detect_cycles();
"""

DROP_DETECT_CYCLES = """\
DROP FUNCTION IF EXISTS detect_cycles();
"""

DROP_TRIGGER_DETECT_CYCLES_ON_INSERT = """\
DROP TRIGGER IF EXISTS detect_cycles_on_insert ON posthog_datamodelingedge;
"""

DROP_TRIGGER_DETECT_CYCLES_ON_UPDATE = """\
DROP TRIGGER IF EXISTS detect_cycles_on_update ON posthog_datamodelingedge;
"""

# detect dag mismatch
CREATE_OR_REPLACE_DETECT_DAG_MISMATCH = """\
CREATE OR REPLACE FUNCTION detect_dag_mismatch()
RETURNS TRIGGER AS $$
DECLARE
    source_team_id BIGINT;
    source_dag_id TEXT;
    target_team_id BIGINT;
    target_dag_id TEXT;
BEGIN
    SELECT team_id INTO source_team_id FROM posthog_datamodelingnode WHERE id = NEW.source_id;
    SELECT team_id INTO target_team_id FROM posthog_datamodelingnode WHERE id = NEW.target_id;
    SELECT dag_id INTO source_dag_id FROM posthog_datamodelingnode WHERE id = NEW.source_id;
    SELECT dag_id INTO target_dag_id FROM posthog_datamodelingnode WHERE id = NEW.target_id;

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

CREATE_TRIGGER_DETECT_DAG_MISMATCH_ON_INSERT = """\
CREATE TRIGGER detect_dag_mismatch_on_insert
BEFORE INSERT ON posthog_datamodelingedge
FOR EACH ROW
EXECUTE FUNCTION detect_dag_mismatch();
"""

CREATE_TRIGGER_DETECT_DAG_MISMATCH_ON_UPDATE = """\
CREATE TRIGGER detect_dag_mismatch_on_update
BEFORE UPDATE OF team_id, dag_id ON posthog_datamodelingedge
FOR EACH ROW
WHEN (OLD.team_id IS DISTINCT FROM NEW.team_id OR OLD.dag_id IS DISTINCT FROM NEW.dag_id)
EXECUTE FUNCTION detect_dag_mismatch();
"""

DROP_DETECT_DAG_MISMATCH = """\
DROP FUNCTION IF EXISTS detect_dag_mismatch();
"""

DROP_TRIGGER_DETECT_DAG_MISMATCH_ON_INSERT = """\
DROP TRIGGER IF EXISTS detect_dag_mismatch_on_insert ON posthog_datamodelingedge;
"""

DROP_TRIGGER_DETECT_DAG_MISMATCH_ON_UPDATE = """\
DROP TRIGGER IF EXISTS detect_dag_mismatch_on_update ON posthog_datamodelingedge;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0002_edge_edge_unique_within_dag"),
    ]

    operations = [
        migrations.RunSQL(CREATE_OR_REPLACE_DETECT_CYCLES, DROP_DETECT_CYCLES),
        migrations.RunSQL(CREATE_TRIGGER_DETECT_CYCLES_ON_INSERT, DROP_TRIGGER_DETECT_CYCLES_ON_INSERT),
        migrations.RunSQL(CREATE_TRIGGER_DETECT_CYCLES_ON_UPDATE, DROP_TRIGGER_DETECT_CYCLES_ON_UPDATE),
        migrations.RunSQL(CREATE_OR_REPLACE_DETECT_DAG_MISMATCH, DROP_DETECT_DAG_MISMATCH),
        migrations.RunSQL(CREATE_TRIGGER_DETECT_DAG_MISMATCH_ON_INSERT, DROP_TRIGGER_DETECT_DAG_MISMATCH_ON_INSERT),
        migrations.RunSQL(CREATE_TRIGGER_DETECT_DAG_MISMATCH_ON_UPDATE, DROP_TRIGGER_DETECT_DAG_MISMATCH_ON_UPDATE),
    ]
