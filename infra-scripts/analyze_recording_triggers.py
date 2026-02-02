#!/usr/bin/env python3
"""
Script to analyze session recording trigger match type usage across teams.

Usage:
    # From within a toolbox pod or local Django environment:
    python infra-scripts/analyze_recording_triggers.py

    # Or via Django shell:
    python manage.py shell < infra-scripts/analyze_recording_triggers.py
"""

import os
import sys
import django

# Setup Django if not already configured
if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    django.setup()

from django.db import connection
from django.db.models import Count, Q
from posthog.models import Team


def analyze_with_orm():
    """Analyze using Django ORM"""
    print("=== Session Recording Trigger Match Type Analysis ===\n")

    # Get counts for each type
    total_teams = Team.objects.count()
    teams_with_any = Team.objects.filter(session_recording_trigger_match_type_config="any").count()
    teams_with_all = Team.objects.filter(session_recording_trigger_match_type_config="all").count()
    teams_with_null = Team.objects.filter(session_recording_trigger_match_type_config__isnull=True).count()

    # Calculate teams with triggers configured (non-null)
    teams_with_triggers = teams_with_any + teams_with_all

    print(f"Total teams: {total_teams}")
    print(f"\nTeams with trigger match type configured: {teams_with_triggers}")
    print(f"  - ANY: {teams_with_any} ({teams_with_any/total_teams*100:.2f}%)")
    print(f"  - ALL: {teams_with_all} ({teams_with_all/total_teams*100:.2f}%)")
    print(f"\nTeams without trigger match type (NULL): {teams_with_null} ({teams_with_null/total_teams*100:.2f}%)")

    # Show ratio among configured teams
    if teams_with_triggers > 0:
        print(f"\nAmong teams with triggers configured:")
        print(f"  - ANY: {teams_with_any/teams_with_triggers*100:.2f}%")
        print(f"  - ALL: {teams_with_all/teams_with_triggers*100:.2f}%")

    return {
        "total": total_teams,
        "any": teams_with_any,
        "all": teams_with_all,
        "null": teams_with_null,
    }


def analyze_with_sql():
    """Analyze using raw SQL for verification"""
    print("\n\n=== SQL Verification ===\n")

    query = """
        SELECT
            session_recording_trigger_match_type_config,
            COUNT(*) as team_count
        FROM posthog_team
        GROUP BY session_recording_trigger_match_type_config
        ORDER BY team_count DESC
    """

    with connection.cursor() as cursor:
        cursor.execute(query)
        results = cursor.fetchall()

        print("Match Type | Team Count")
        print("-" * 30)
        for match_type, count in results:
            match_type_display = match_type if match_type else "NULL"
            print(f"{match_type_display:10} | {count}")

    return results


if __name__ == "__main__":
    try:
        orm_results = analyze_with_orm()
        sql_results = analyze_with_sql()

        print("\n✅ Analysis complete!")
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
