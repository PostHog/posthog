from django.db import migrations

MODELS_TO_MOVE = ("changerequest", "approvalpolicy", "approval")


def _move_content_types(apps, schema_editor, from_label, to_label):
    """Move ContentTypes between apps, handling duplicates idempotently."""
    db_alias = schema_editor.connection.alias
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")

    for model_name in MODELS_TO_MOVE:
        source = ContentType.objects.using(db_alias).filter(app_label=from_label, model=model_name).first()
        target = ContentType.objects.using(db_alias).filter(app_label=to_label, model=model_name).first()

        if source and target:
            Permission.objects.using(db_alias).filter(content_type=source).update(content_type=target)
            source.delete(using=db_alias)
        elif source:
            source.app_label = to_label
            source.save(using=db_alias)


def update_content_types(apps, schema_editor):
    _move_content_types(apps, schema_editor, "posthog", "approvals")


def reverse_content_types(apps, schema_editor):
    _move_content_types(apps, schema_editor, "approvals", "posthog")


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0001_migrate_approvals_models"),
        ("posthog", "1238_ducklakebackfill_earliest_event_date"),
    ]

    # State-only move: the approval models now live in the `approvals` app
    # (products/approvals/backend). database_operations is empty — the physical tables are
    # untouched; products/approvals/backend/migrations/0001_migrate_approvals_models.py
    # recreates them in ORM state under the `approvals` app. The RunPython below repoints
    # existing django_content_type / auth_permission rows from the posthog label to approvals.
    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterUniqueTogether(
                    name="approvalpolicy",
                    unique_together=None,
                ),
                migrations.RemoveField(
                    model_name="approvalpolicy",
                    name="bypass_roles",
                ),
                migrations.RemoveField(
                    model_name="approvalpolicy",
                    name="created_by",
                ),
                migrations.RemoveField(
                    model_name="approvalpolicy",
                    name="organization",
                ),
                migrations.RemoveField(
                    model_name="approvalpolicy",
                    name="team",
                ),
                migrations.RemoveField(
                    model_name="changerequest",
                    name="applied_by",
                ),
                migrations.RemoveField(
                    model_name="changerequest",
                    name="created_by",
                ),
                migrations.RemoveField(
                    model_name="changerequest",
                    name="organization",
                ),
                migrations.RemoveField(
                    model_name="changerequest",
                    name="team",
                ),
                migrations.DeleteModel(
                    name="Approval",
                ),
                migrations.DeleteModel(
                    name="ApprovalPolicy",
                ),
                migrations.DeleteModel(
                    name="ChangeRequest",
                ),
            ],
            database_operations=[],
        ),
        migrations.RunPython(update_content_types, reverse_content_types),
    ]
