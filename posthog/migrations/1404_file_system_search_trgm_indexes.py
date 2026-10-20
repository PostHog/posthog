import django.contrib.postgres.indexes
import django.db.models.functions.text
from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1403_project_logo_media_index"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="filesystem",
            index=django.contrib.postgres.indexes.GinIndex(
                django.contrib.postgres.indexes.OpClass(
                    django.db.models.functions.text.Lower(
                        django.db.models.functions.text.Concat(
                            models.F("path"),
                            models.Value(" "),
                            models.F("type"),
                            output_field=models.TextField(),
                        )
                    ),
                    name="gin_trgm_ops",
                ),
                name="posthog_fs_search_text_trgm",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="filesystem",
            index=django.contrib.postgres.indexes.GinIndex(
                django.contrib.postgres.indexes.OpClass(
                    django.db.models.functions.text.Lower(
                        models.Func(
                            models.F("path"),
                            models.Value("^.*/"),
                            models.Value(""),
                            function="regexp_replace",
                            output_field=models.TextField(),
                        )
                    ),
                    name="gin_trgm_ops",
                ),
                name="posthog_fs_search_name_trgm",
            ),
        ),
    ]
