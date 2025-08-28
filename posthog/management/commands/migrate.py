from django.core.management.commands.migrate import Command as MigrateCommand


class Command(MigrateCommand):
    def handle(self, *args, **options):
        return super().handle(*args, **options)
