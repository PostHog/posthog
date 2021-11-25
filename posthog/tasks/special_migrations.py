from posthog.celery import app
from posthog.models.special_migration import get_all_running_special_migrations
from posthog.special_migrations.runner import run_special_migration_next_op, start_special_migration


# we're hijacking an entire worker to do this - consider:
# 1. spawning a thread within the worker
# 2. suggesting users scale celery when running special migrations
# 3. ...
@app.task(ignore_result=False, max_retries=0)
def run_special_migration(migration_name: str, start=True) -> None:
    if start:
        start_special_migration(migration_name)
        return

    # TODO: Implement resumable operations
    run_special_migration_next_op(migration_name)
