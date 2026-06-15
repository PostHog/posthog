import os
import re

from django.core.management.base import BaseCommand
from django.utils.timezone import now

CORE_MIGRATION_PATH = "posthog/clickhouse/migrations"

FILE_DEFAULT = """
from infi.clickhouse_orm import migrations # type: ignore
operations = []
"""


# ex: python manage.py create_ch_migration <name of migration> [--product logs]
class Command(BaseCommand):
    help = "Create blank clickhouse migration"

    def add_arguments(self, parser):
        parser.add_argument("--name", type=str)
        parser.add_argument("--product", type=str, help="Product name; omit for core migrations")

    def handle(self, *args, **options):
        name = options["name"]
        product = options["product"]

        path = f"products/{product}/backend/clickhouse/migrations" if product else CORE_MIGRATION_PATH

        # default to auto syntax
        if not name:
            name = now().strftime("auto_%Y%m%d_%H%M")

        index_label = _format_number(_next_index(path))
        module_name = f"{index_label}_{name}"
        file_name = f"{path}/{module_name}.py"
        with open(file_name, "w", encoding="utf_8") as f:
            f.write(FILE_DEFAULT)
        with open(f"{path}/max_migration.txt", "w", encoding="utf_8") as f:
            f.write(module_name)
        self.stdout.write(f"Created {file_name}")


def _next_index(path: str) -> int:
    highest = 0
    for filename in os.listdir(path):
        match = re.match(r"([0-9]+)_", filename)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def _format_number(num: int) -> str:
    return str(num).zfill(4)
