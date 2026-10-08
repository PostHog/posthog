from django.db import migrations, models


def backfill_playground_sandbox_runs(apps, schema_editor):
    PlaygroundChat = apps.get_model("business_knowledge", "PlaygroundChat")
    PlaygroundTurn = apps.get_model("business_knowledge", "PlaygroundTurn")
    TaskRun = apps.get_model("tasks", "TaskRun")
    # Materialize ids first. A server-side cursor cannot share this migration's
    # transaction with the per-chat reads and writes below.
    chat_ids = list(PlaygroundChat.objects.values_list("id", flat=True))
    for chat_id in chat_ids:
        chat = PlaygroundChat.objects.get(id=chat_id)
        latest_turn = PlaygroundTurn.objects.filter(chat_id=chat.id).order_by("-position").first()
        if latest_turn is None:
            continue
        if chat.task_id is None:
            chat.task_id = latest_turn.task_id
            chat.save(update_fields=["task_id"])
        turns = list(PlaygroundTurn.objects.filter(chat_id=chat.id, run_id__isnull=True))
        for turn in turns:
            run_id = (
                TaskRun.objects.filter(task_id=turn.task_id)
                .order_by("-created_at", "-id")
                .values_list("id", flat=True)
                .first()
            )
            if run_id is None:
                continue
            turn.run_id = run_id
            turn.save(update_fields=["run_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("business_knowledge", "0021_teambusinessknowledgeconfig_github_repos"),
        ("tasks", "0001_squash_2026_09_07_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="playgroundchat",
            name="task_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="playgroundturn",
            name="run_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.RemoveConstraint(
            model_name="playgroundturn",
            name="bk_pg_turn_task_id",
        ),
        migrations.RunPython(backfill_playground_sandbox_runs, migrations.RunPython.noop),
    ]
