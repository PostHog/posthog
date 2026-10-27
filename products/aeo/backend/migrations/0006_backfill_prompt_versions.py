from django.db import migrations

BATCH_SIZE = 1000


def create_first_versions(apps, schema_editor) -> None:
    AEOPrompt = apps.get_model("aeo", "AEOPrompt")
    AEOPromptVersion = apps.get_model("aeo", "AEOPromptVersion")
    last_id = None
    while True:
        # Keyset pages keep each read small however large the table is.
        batch = AEOPrompt.objects.order_by("id")
        if last_id is not None:
            batch = batch.filter(id__gt=last_id)
        rows = list(batch.values("id", "team_id", "created_by_id", "created_at", "prompt")[:BATCH_SIZE])
        if not rows:
            return
        # ignore_conflicts makes a rerun after a partial failure skip the versions it already wrote.
        versions = AEOPromptVersion.objects.bulk_create(
            [
                AEOPromptVersion(
                    prompt_id=row["id"],
                    team_id=row["team_id"],
                    created_by_id=row["created_by_id"],
                    version=1,
                    text=row["prompt"],
                )
                for row in rows
            ],
            ignore_conflicts=True,
        )
        # auto_now_add stamps the insert with the migration time; bulk_update skips it, so version 1
        # takes the prompt's own creation time. Rows skipped as conflicts match no id and stay as they are.
        created_at = {row["id"]: row["created_at"] for row in rows}
        for version in versions:
            version.created_at = created_at[version.prompt_id]
        AEOPromptVersion.objects.bulk_update(versions, ["created_at"])
        last_id = rows[-1]["id"]


class Migration(migrations.Migration):
    dependencies = [
        ("aeo", "0005_prompt_versions_and_archive"),
    ]

    operations = [
        migrations.RunPython(create_first_versions, reverse_code=migrations.RunPython.noop),
    ]
