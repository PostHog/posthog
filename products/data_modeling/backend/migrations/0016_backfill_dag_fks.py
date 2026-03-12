from django.db import connection, migrations


def backfill_node_dag_fks(apps, _schema_editor):
    DAG = apps.get_model("data_modeling", "DAG")
    Node = apps.get_model("data_modeling", "Node")

    batch_size = 1000
    dag_lookup: dict[tuple[int, str], object] = {}
    for dag in DAG.objects.all():
        dag_lookup[(dag.team_id, dag.name)] = dag.id

    nodes_to_update = []
    for node in Node.objects.filter(dag_fk__isnull=True).iterator(chunk_size=batch_size):
        dag_id = dag_lookup.get((node.team_id, node.dag_id_text))
        if dag_id is None:
            continue
        node.dag_fk_id = dag_id
        nodes_to_update.append(node)
        if len(nodes_to_update) >= batch_size:
            Node.objects.bulk_update(nodes_to_update, ["dag_fk_id"], batch_size=batch_size)
            nodes_to_update = []
    if nodes_to_update:
        Node.objects.bulk_update(nodes_to_update, ["dag_fk_id"], batch_size=batch_size)


def backfill_edge_dag_fks(apps, _schema_editor):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE posthog_datamodelingedge e
            SET dag_fk_id = d.id
            FROM posthog_datamodelingdag d
            WHERE e.team_id = d.team_id
              AND e.dag_id_text = d.name
              AND e.dag_fk_id IS NULL
            """
        )


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0015_add_dag_fk_indexes"),
    ]

    operations = [
        migrations.RunPython(backfill_node_dag_fks, migrations.RunPython.noop),
        migrations.RunPython(backfill_edge_dag_fks, migrations.RunPython.noop),
    ]
