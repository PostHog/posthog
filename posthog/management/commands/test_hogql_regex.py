"""
Test HogQL regex patterns to understand what's supported
Usage: python manage.py test_hogql_regex
"""

from django.core.management.base import BaseCommand

from posthog.hogql.query import execute_hogql_query

from posthog.models import Team


class Command(BaseCommand):
    help = "Test various HogQL regex patterns to understand what's supported"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, help="Team ID to use for testing", default=1)

    def handle(self, *args, **options):
        team_id = options["team_id"]

        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Team {team_id} does not exist"))
            return

        self.stdout.write(self.style.SUCCESS(f"\nTesting HogQL regex patterns for team {team_id}\n"))
        self.stdout.write("=" * 70)

        # Test patterns
        test_cases = [
            ("Simple +", "[0-9]+", "NUM", "12345"),
            ("Exact {3}", "[0-9]{3}", "NUM", "123"),
            ("Exact {5}", "[0-9]{5}", "NUM", "12345"),
            ("Range {3,5}", "[0-9]{3,5}", "NUM", "12345"),
            ("Open {3,}", "[0-9]{3,}", "NUM", "12345"),
            ("Open {13,}", "[0-9]{13,}", "TIMESTAMP", "1699452899655"),
            ("Word boundary \\b", "\\b[0-9]+\\b", "NUM", "123"),
            (
                "UUID pattern",
                "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                "UUID",
                "550e8400-e29b-41d4-a716-446655440000",
            ),
            (
                "ISO timestamp",
                "[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3,6}Z?",
                "TIMESTAMP",
                "2025-11-08T14:14:59.655Z",
            ),
            (
                "ISO timestamp +",
                "[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]+Z?",
                "TIMESTAMP",
                "2025-11-08T14:14:59.655Z",
            ),
            ("Request ID", "req_[a-zA-Z0-9]+", "REQ_ID", "req_4eaf36431a034e73bad025076aedc2cc"),
            ("Negated class", "[^,}]+", "ID", "responseId:abc"),
            ("responseId pattern", "responseId[^,}]+", "responseId:RESPONSE_ID", "responseId:_E4Paf3yKeWXgLUPwLGRuQ4"),
            (
                "Explicit digits 13x",
                "[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]+",
                "TIMESTAMP",
                "1699452899655",
            ),
            (
                "Project path",
                "projects/[0-9]+/locations/[^/]+/publishers/[^/]+/models/[a-zA-Z0-9._-]+",
                "projects/<ID>/locations/<REGION>/publishers/<PUBLISHER>/models/<MODEL>",
                "projects/986903089694/locations/us-west2/publishers/deepseek/models/deepseek-v3.1-maas",
            ),
        ]

        # Test HogQL functions for WITH approach
        self.stdout.write("\n\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS("\nTesting HogQL Functions for WITH pattern:\n"))

        function_tests = [
            ("nullIf", "SELECT nullIf('test', '') as result"),
            ("coalesce", "SELECT coalesce(null, 'fallback') as result"),
            ("trim BOTH", "SELECT trim(BOTH ' ' FROM '  test  ') as result"),
            ("lowerUTF8", "SELECT lowerUTF8('TEST') as result"),
            ("WITH clause", "WITH x AS (SELECT 'test' as val) SELECT val FROM x"),
        ]

        for name, query in function_tests:
            self.stdout.write(f"\n{name}")
            try:
                result = execute_hogql_query(query=query, team=team)
                if result.results and len(result.results) > 0:
                    self.stdout.write(self.style.SUCCESS(f"  ✓ Works: {result.results[0][0]}"))
                else:
                    self.stdout.write(self.style.WARNING(f"  ⚠ No results"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ✗ Not supported: {str(e)[:100]}"))

        for name, pattern, replacement, test_input in test_cases:
            self.stdout.write(f"\n{name}")
            self.stdout.write(f"  Pattern: {pattern}")
            self.stdout.write(f"  Input: {test_input}")
            self.stdout.write(f"  Expected: {replacement}")

            query = f"SELECT replaceRegexpAll('{test_input}', '{pattern}', '{replacement}') as result"

            try:
                result = execute_hogql_query(
                    query=query,
                    team=team,
                )

                if result.results and len(result.results) > 0:
                    actual_result = result.results[0][0]
                    if actual_result == replacement:
                        self.stdout.write(self.style.SUCCESS(f"  ✓ Result: {actual_result}"))
                    else:
                        self.stdout.write(self.style.WARNING(f"  ⚠ Result: {actual_result} (expected {replacement})"))
                else:
                    self.stdout.write(self.style.WARNING(f"  ⚠ No results returned"))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ✗ Error: {str(e)[:200]}"))

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS("\nTest complete!\n"))
