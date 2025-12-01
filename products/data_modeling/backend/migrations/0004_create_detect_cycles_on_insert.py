# manually created by andrewjmcgehee

from django.db import migrations

DROP_TRIGGER_DETECT_CYCLES_ON_INSERT = """\
DROP TRIGGER IF EXISTS posthog_datamodelingedge_detect_cycles_on_insert ON posthog_datamodelingedge;
"""

# workaround for create trigger if not exists is to drop if exists and then create
CREATE_TRIGGER_DETECT_CYCLES_ON_INSERT = f"""\
{DROP_TRIGGER_DETECT_CYCLES_ON_INSERT}
CREATE TRIGGER posthog_datamodelingedge_detect_cycles_on_insert
BEFORE INSERT ON posthog_datamodelingedge
FOR EACH ROW
EXECUTE FUNCTION posthog_datamodelingedge_detect_cycles();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0003_create_detect_cycles_function"),
    ]

    operations = [
        migrations.RunSQL(CREATE_TRIGGER_DETECT_CYCLES_ON_INSERT, DROP_TRIGGER_DETECT_CYCLES_ON_INSERT),
    ]
