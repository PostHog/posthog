from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit


@shared_task(ignore_result=True)
@skip_team_scope_audit
def cleanup_deleted_saved_query_nodes() -> None:
    from products.data_modeling.backend.logic.saved_query_dag_sync import (
        delete_deleted_saved_query_nodes_for_teams,
        deleted_saved_query_nodes,
    )

    delete_deleted_saved_query_nodes_for_teams(set(deleted_saved_query_nodes().values_list("team_id", flat=True)))
