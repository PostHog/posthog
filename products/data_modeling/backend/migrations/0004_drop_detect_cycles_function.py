# manually created by andrewjmcgehee

from django.db import migrations

DROP_DETECT_CYCLES = """\
DROP FUNCTION IF EXISTS posthog_datamodelingedge_detect_cycles();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0003_create_detect_cycles_function"),
    ]
    operations = [migrations.RunSQL(DROP_DETECT_CYCLES)]
