# manually created by andrewjmcgehee

from django.db import migrations

# detect cycles
CREATE_OR_REPLACE_DETECT_CYCLES = """\
CREATE OR REPLACE FUNCTION posthog_datamodelingedge_detect_cycles()
RETURNS TRIGGER AS $$
BEGIN
  -- acquire team_id, dag_id scoped lock
  PERFORM pg_advisory_xact_lock(
    NEW.team_id,
    hashtext(NEW.dag_id)
  );

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

DROP_DETECT_CYCLES = """\
DROP FUNCTION IF EXISTS prosthog_datamodelingedge_detect_cycles();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0002_edge_edge_unique_within_dag"),
    ]

    operations = [
        migrations.RunSQL(CREATE_OR_REPLACE_DETECT_CYCLES, DROP_DETECT_CYCLES),
    ]
