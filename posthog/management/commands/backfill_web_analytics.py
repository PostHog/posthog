from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import color_style

from posthog.models import Team
from posthog.tasks.web_analytics_backfill import (
    backfill_web_analytics_tables_for_team,
    validate_backfill_data_integrity,
    cleanup_corrupted_backfill_data,
    get_backfill_date_range,
)


class Command(BaseCommand):
    help = """
    Manage web analytics pre-aggregated table backfills.
    
    This command provides manual control over backfill operations for teams
    that have enabled web analytics pre-aggregated tables.
    """
    
    def __init__(self):
        super().__init__()
        self.style = color_style()

    def add_arguments(self, parser):
        parser.add_argument(
            'action',
            choices=['backfill', 'validate', 'cleanup', 'list'],
            help='Action to perform'
        )
        
        parser.add_argument(
            '--team-id',
            type=int,
            help='Specific team ID to process'
        )
        
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='Number of days to backfill (default: 7, max: 30)'
        )
        
        parser.add_argument(
            '--date-start',
            help='Start date in YYYY-MM-DD format (for validate/cleanup actions)'
        )
        
        parser.add_argument(
            '--date-end',
            help='End date in YYYY-MM-DD format (for validate/cleanup actions)'
        )
        
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without executing'
        )
        
        parser.add_argument(
            '--async',
            action='store_true',
            help='Execute backfill asynchronously via Celery'
        )

    def handle(self, *args, **options):
        action = options['action']
        
        if action == 'list':
            self.list_teams_with_pre_aggregated_tables()
        elif action == 'backfill':
            self.handle_backfill(options)
        elif action == 'validate':
            self.handle_validate(options)
        elif action == 'cleanup':
            self.handle_cleanup(options)

    def list_teams_with_pre_aggregated_tables(self):
        """List all teams that have web analytics pre-aggregated tables enabled."""
        teams = Team.objects.filter(web_analytics_pre_aggregated_tables_enabled=True)
        
        if not teams.exists():
            self.stdout.write(
                self.style.WARNING("No teams have web analytics pre-aggregated tables enabled.")
            )
            return
        
        self.stdout.write(
            self.style.SUCCESS(f"Found {teams.count()} teams with pre-aggregated tables enabled:")
        )
        
        for team in teams:
            self.stdout.write(f"  - Team {team.id}: {team.name} (org: {team.organization.name})")

    def handle_backfill(self, options):
        """Handle backfill action."""
        team_id = options.get('team_id')
        days = options.get('days', 7)
        dry_run = options.get('dry_run', False)
        async_exec = options.get('async', False)
        
        if not team_id:
            raise CommandError("--team-id is required for backfill action")
        
        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team {team_id} not found")
        
        if not team.web_analytics_pre_aggregated_tables_enabled:
            raise CommandError(
                f"Team {team_id} does not have web analytics pre-aggregated tables enabled"
            )
        
        date_start, date_end = get_backfill_date_range(days)
        
        self.stdout.write(
            f"{'[DRY RUN] ' if dry_run else ''}Backfill plan for Team {team_id} ({team.name}):"
        )
        self.stdout.write(f"  - Date range: {date_start} to {date_end}")
        self.stdout.write(f"  - Days: {days}")
        self.stdout.write(f"  - Execution: {'Async (Celery)' if async_exec else 'Sync (Direct)'}")
        
        if dry_run:
            self.stdout.write(self.style.SUCCESS("Dry run completed. Use --no-dry-run to execute."))
            return
        
        if async_exec:
            # Execute via Celery
            task = backfill_web_analytics_tables_for_team.delay(team_id, days)
            self.stdout.write(
                self.style.SUCCESS(f"Backfill task queued with ID: {task.id}")
            )
        else:
            # Execute synchronously
            try:
                result = backfill_web_analytics_tables_for_team(team_id, days)
                if result.get("status") == "completed":
                    self.stdout.write(
                        self.style.SUCCESS(f"Backfill completed successfully for team {team_id}")
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR(f"Backfill failed: {result}")
                    )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Backfill failed with exception: {str(e)}")
                )

    def handle_validate(self, options):
        """Handle validate action."""
        team_id = options.get('team_id')
        date_start = options.get('date_start')
        date_end = options.get('date_end')
        
        if not team_id:
            raise CommandError("--team-id is required for validate action")
        
        if not date_start or not date_end:
            # Use default 7-day range if not specified
            date_start, date_end = get_backfill_date_range(7)
            self.stdout.write(f"Using default date range: {date_start} to {date_end}")
        
        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team {team_id} not found")
        
        self.stdout.write(f"Validating backfill data for Team {team_id} ({team.name})...")
        
        try:
            result = validate_backfill_data_integrity(team_id, date_start, date_end)
            
            if result.get("status") == "completed":
                self.stdout.write(self.style.SUCCESS("Validation completed:"))
                for metric, value in result["validation_results"].items():
                    self.stdout.write(f"  - {metric}: {value:,} rows")
            else:
                self.stdout.write(
                    self.style.ERROR(f"Validation failed: {result.get('error', 'Unknown error')}")
                )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Validation failed with exception: {str(e)}")
            )

    def handle_cleanup(self, options):
        """Handle cleanup action."""
        team_id = options.get('team_id')
        date_start = options.get('date_start')
        date_end = options.get('date_end')
        dry_run = options.get('dry_run', False)
        
        if not team_id:
            raise CommandError("--team-id is required for cleanup action")
        
        if not date_start or not date_end:
            raise CommandError("--date-start and --date-end are required for cleanup action")
        
        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team {team_id} not found")
        
        self.stdout.write(
            self.style.WARNING(
                f"{'[DRY RUN] ' if dry_run else ''}This will DELETE backfilled data and DISABLE pre-aggregated tables"
            )
        )
        self.stdout.write(f"  - Team: {team_id} ({team.name})")
        self.stdout.write(f"  - Date range: {date_start} to {date_end}")
        
        if dry_run:
            self.stdout.write(self.style.SUCCESS("Dry run completed. Use --no-dry-run to execute."))
            return
        
        # Ask for confirmation
        confirm = input("Are you sure you want to proceed? Type 'yes' to continue: ")
        if confirm.lower() != 'yes':
            self.stdout.write("Operation cancelled.")
            return
        
        try:
            result = cleanup_corrupted_backfill_data(team_id, date_start, date_end)
            
            if result.get("status") == "cleaned_up":
                self.stdout.write(
                    self.style.SUCCESS(f"Cleanup completed for team {team_id}")
                )
                self.stdout.write("Pre-aggregated tables have been disabled for this team.")
            else:
                self.stdout.write(
                    self.style.ERROR(f"Cleanup failed: {result.get('error', 'Unknown error')}")
                )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Cleanup failed with exception: {str(e)}")
            )