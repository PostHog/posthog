import django.db.models.deletion
import django.contrib.postgres.search
import django.contrib.postgres.indexes
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("context_layer", "0007_contextselectionprojection"),
    ]

    operations = [
        migrations.CreateModel(
            name="ContextSelectionSearchState",
            fields=[
                (
                    "id",
                    models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
                ),
                ("version", models.CharField(max_length=64)),
                ("archive_id", models.UUIDField()),
                ("built_at", models.DateTimeField()),
                ("refresh_seconds", models.FloatField()),
                (
                    "team",
                    models.OneToOneField(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ContextSelectionSearchDocument",
            fields=[
                (
                    "id",
                    models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
                ),
                ("source_kind", models.CharField(max_length=32)),
                ("source_id", models.CharField(max_length=64)),
                ("title", models.TextField()),
                ("text", models.TextField()),
                ("revision", models.CharField(max_length=128)),
                ("status", models.CharField(max_length=64)),
                ("reference", models.TextField()),
                ("tables", models.JSONField(default=list)),
                ("search_vector", django.contrib.postgres.search.SearchVectorField(null=True)),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "indexes": [
                    django.contrib.postgres.indexes.GinIndex(fields=["search_vector"], name="context_search_vector_gin")
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("team", "source_kind", "source_id"), name="context_search_source")
                ],
            },
        ),
    ]
