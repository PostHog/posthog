import django.contrib.postgres.indexes
from django.db import migrations

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("data_modeling", "0031_datamodelingjob_run_mode"),
        # the GiST index mixes an integer column with an ltree column, which needs btree_gist
        ("posthog", "0308_add_indirect_person_override_constraints"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="datawarehousemodelpath",
            index=django.contrib.postgres.indexes.GistIndex(fields=["team_id", "path"], name="model_path_team_id_path"),
        ),
    ]
