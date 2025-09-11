import os

from django.core.management.base import BaseCommand
from django.utils.timezone import now

MIGRATION_PATH = "ee/clickhouse/migrations"

FILE_DEFAULT = """
from infi.clickhouse_orm import migrations # type: ignore
operations = []
"""


# ex: python manage.py create_ch_migration <name of migration>
class Command(BaseCommand):
    help = "Create blank clickhouse migration"

    def add_arguments(self, parser):
        parser.add_argument("--name", type=str)

    def handle(self, *args, **options):
        name = options["name"]

        # default to auto syntax
        if not name:
            name = now().strftime("auto_%Y%m%d_%H%M.py")
        else:
            name += ".py"

        entries = os.listdir(MIGRATION_PATH)

        idx = len(entries)
        index_label = _format_number(idx)
        file_name = "{}/{}_{}".format(MIGRATION_PATH, index_label, name)
        with open(file_name, "w", encoding="utf_8") as f:
            f.write(FILE_DEFAULT)
        return


def _format_number(num: int) -> str:
    if num < 10:
        return "000" + str(num)
    elif num < 100:
        return "00" + str(num)
    elif num < 1000:
        return "0" + str(num)
    else:
        return str(num)
