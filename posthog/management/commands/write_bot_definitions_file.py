from django.core.management.base import BaseCommand

from posthog.models.bot_definition.sql import BOT_DEFINITIONS_FILE, bot_definitions_file_content


class Command(BaseCommand):
    help = (
        "Write the rows of the web_bot_definition table, from BOT_DEFINITIONS, to the file the ClickHouse schema loads."
    )

    def handle(self, *args, **options) -> None:
        BOT_DEFINITIONS_FILE.write_text(bot_definitions_file_content())
        self.stdout.write(f"Wrote {BOT_DEFINITIONS_FILE}")
