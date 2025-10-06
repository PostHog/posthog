from django.core.management.base import BaseCommand
from django.db import connection

from posthog.models import HogFunction


class Command(BaseCommand):
    help = "Re-enables HogFunctions that are connected to integrations by triggering a reload on the plugin server"

    def handle(self, *args, **options):
        # SQL query to get HogFunctions connected to integrations
        query = """
        SELECT DISTINCT hf.id
        FROM posthog_hogfunction hf
        CROSS JOIN LATERAL jsonb_array_elements(hf.inputs_schema) AS schema
        JOIN posthog_integration i
        ON i.id = CAST((hf.inputs -> (schema->>'key')) ->> 'value' AS INTEGER)
        WHERE jsonb_typeof(hf.inputs) IS NOT NULL
        AND schema->>'type' = 'integration'
        AND i.config::jsonb ? 'refreshed_at'
        AND hf.enabled = true
        AND hf.deleted = false
        """

        with connection.cursor() as cursor:
            cursor.execute(query)
            hog_function_ids = [row[0] for row in cursor.fetchall()]

        count = 0
        for function in HogFunction.objects.filter(id__in=hog_function_ids):
            function.save(update_fields=["updated_at"])  # Minimal save to trigger the signal
            count += 1
            self.stdout.write(f"Triggered reload for HogFunction {function.id}")

        self.stdout.write(self.style.SUCCESS(f"Successfully triggered reload for {count} HogFunctions"))
