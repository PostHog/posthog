import django.db.models.functions.text
from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1386_taggeditem_drop_legacy_columns"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="user",
            index=models.Index(
                django.db.models.functions.text.Replace(
                    models.Func(
                        models.Func(
                            django.db.models.functions.text.Lower("email"),
                            models.Value("\\+[^@]*@"),
                            models.Value("@"),
                            function="regexp_replace",
                        ),
                        models.Value("@"),
                        models.Value(1),
                        function="split_part",
                        output_field=models.CharField(),
                    ),
                    models.Value("."),
                    models.Value(""),
                ),
                name="user_gmail_canonical_idx",
            ),
        ),
    ]
