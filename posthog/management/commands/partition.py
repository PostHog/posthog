from django.core.management.base import BaseCommand
import os
from django.db import connection

def load_sql(filename):
    path = os.path.join(os.path.dirname(__file__), '../sql/', filename)
    return open(path).read()

class Command(BaseCommand):
    help = 'Migrate data to new model'

    def add_arguments(self, parser):
        parser.add_argument('--element', default=[], dest='element', action='append')
        parser.add_argument('--reverse', action='store_true', help='unpartition event table')

    def handle(self, *args, **options):

        if options['reverse']:
            with connection.cursor() as cursor:
                cursor.execute(load_sql('0050_event_partitions_reverse.sql'))
            return
        
        elements = []
        if options['element']:
            elements = options['element']

        if connection.cursor().connection.server_version >= 120000:
            with connection.cursor() as cursor:
                print("Partitioning...")
                cursor.execute(load_sql('0050_event_partitions.sql'))
                cursor.execute("""DO $$ BEGIN IF (SELECT exists(select * from pg_proc where proname = \'create_partitions\')) THEN PERFORM create_partitions(%s); END IF; END $$""", [elements])