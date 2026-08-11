"""Retire the home-canvas concept (schema side; 0007 soft-deleted the rows).

The partial unique constraint is dropped for real; the column itself is
removed from Django state only (per safe-migration policy) and given a
database-side default first, so inserts that no longer mention it keep
working. A later migration may drop the column physically.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("canvas", "0007_soft_delete_home_canvases"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="canvas",
            name="unique_home_canvas_per_channel",
        ),
        migrations.AlterField(
            model_name="canvas",
            name="is_home",
            field=models.BooleanField(default=False, db_default=False),
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveField(model_name="canvas", name="is_home"),
            ],
        ),
    ]
