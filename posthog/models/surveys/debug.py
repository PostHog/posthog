from typing import Any

from posthog.api.team import CachingTeamSerializer
from posthog.models.team import Team
from posthog.models.team.team_caching import get_team_in_cache, set_team_in_cache


def check_team_cache_consistency(team_id_or_token: str) -> dict[str, Any]:
    """
    Check for inconsistencies between the database and cache for a specific team's settings.
    Args:
        team_id_or_token: The team ID or API token
    Returns:
        Dict with information about the team and any inconsistencies
    """
    result: dict[str, Any] = {
        "team_id": None,
        "team_name": None,
        "has_inconsistency": False,
        "inconsistent_fields": [],
        "db_values": {},
        "cache_values": {},
        "fixed": False,
    }

    # Try to get team by ID or token
    try:
        try:
            team_id = int(team_id_or_token)
            team = Team.objects.get(id=team_id)
        except ValueError:
            team = Team.objects.get(api_token=team_id_or_token)

        result["team_id"] = team.id
        result["team_name"] = team.name

        # Get team from cache
        cached_team = get_team_in_cache(team.api_token)

        if cached_team:
            # Get serialized data for both DB and cache
            db_serialized = CachingTeamSerializer(team).data
            cache_serialized = CachingTeamSerializer(cached_team).data

            # Check for inconsistencies across all fields
            for key in db_serialized:
                db_value = db_serialized[key]
                cache_value = cache_serialized.get(key)

                if db_value != cache_value:
                    result["has_inconsistency"] = True
                    result["inconsistent_fields"].append(key)
                    result["db_values"][key] = db_value
                    result["cache_values"][key] = cache_value

            if result["has_inconsistency"]:
                print(f"Inconsistency found for team {team.id} ({team.name}):")  # noqa: T201
                for field in result["inconsistent_fields"]:
                    print(f"  - {field}: DB={result['db_values'][field]}, Cache={result['cache_values'][field]}")  # noqa: T201
        else:
            print(f"Team {team.id} not found in cache")  # noqa: T201

    except Team.DoesNotExist:
        print(f"Team with ID/token {team_id_or_token} not found")  # noqa: T201

    return result


def fix_team_cache_consistency(team_id_or_token: str) -> dict[str, Any]:
    """
    Fix inconsistencies between the database and cache for a specific team's settings.
    Args:
        team_id_or_token: The team ID or API token
    Returns:
        Dict with information about the team and the fix operation
    """
    result = check_team_cache_consistency(team_id_or_token)

    if result["has_inconsistency"]:
        try:
            # Get the team again to ensure we have the latest data
            team = Team.objects.get(id=result["team_id"])

            # Update the cache
            set_team_in_cache(team.api_token, team)
            result["fixed"] = True

            print(f"Fixed cache for team {team.id}")  # noqa: T201

            # Verify the fix
            cached_team = get_team_in_cache(team.api_token)
            if cached_team:
                # Re-check if all fields are now consistent
                db_serialized = CachingTeamSerializer(team).data
                cache_serialized = CachingTeamSerializer(cached_team).data

                all_fixed = True
                remaining_inconsistencies: list[str] = []

                for key in result["inconsistent_fields"]:
                    if db_serialized[key] != cache_serialized.get(key):
                        all_fixed = False
                        remaining_inconsistencies.append(key)

                if all_fixed:
                    print(f"Verified: Cache now has correct values for all fields")  # noqa: T201
                else:
                    print(f"Warning: Cache still has inconsistencies for fields: {remaining_inconsistencies}")  # noqa: T201
            else:
                print(f"Warning: Team not found in cache after fix attempt")  # noqa: T201
        except Exception as e:
            print(f"Error fixing cache: {str(e)}")  # noqa: T201
    else:
        print("No inconsistency found, no fix needed")  # noqa: T201

    return result


def find_teams_with_cache_inconsistencies(
    batch_size: int = 100, only_active_surveys: bool = True
) -> list[dict[str, Any]]:
    """
    Find all teams with cache inconsistencies between database and cache.
    Args:
        batch_size: Number of teams to process in each batch.
        only_active_surveys: If True, only check teams with active surveys.
    Returns:
        List of dictionaries with information about teams with inconsistencies
    """
    from posthog.models.surveys.survey import Survey

    inconsistent_teams: list[dict[str, Any]] = []
    teams_checked = 0
    teams_in_cache = 0
    inconsistency_counts: dict[str, int] = {}

    # Variables used in both branches
    inconsistent_fields: list[str] = []
    db_values: dict[str, Any] = {}
    cache_values: dict[str, Any] = {}
    team_info: dict[str, Any] = {}

    # Get teams to check
    if only_active_surveys:
        # Get teams with active surveys using Django ORM
        team_ids_with_active_surveys = (
            Survey.objects.filter(start_date__isnull=False, end_date__isnull=True, archived=False)
            .values_list("team_id", flat=True)
            .distinct()
        )

        # Count teams with active surveys
        total_teams = len(team_ids_with_active_surveys)
        print(f"Checking cache consistency for {total_teams} teams with active surveys...")  # noqa: T201

        # Process teams in batches to avoid memory issues
        for i in range(0, len(team_ids_with_active_surveys), batch_size):
            batch_ids = team_ids_with_active_surveys[i : i + batch_size]
            teams_batch = Team.objects.filter(id__in=batch_ids)

            for team in teams_batch:
                teams_checked += 1

                # Print progress
                if teams_checked % 50 == 0 or teams_checked == total_teams:
                    progress_pct = (teams_checked / total_teams) * 100 if total_teams > 0 else 0
                    print(f"Progress: {teams_checked}/{total_teams} teams checked ({progress_pct:.1f}%)")  # noqa: T201

                # Get team from cache
                cached_team = get_team_in_cache(team.api_token)

                # Skip teams not in cache
                if not cached_team:
                    continue

                teams_in_cache += 1

                # Check for inconsistencies across all fields
                db_serialized = CachingTeamSerializer(team).data
                cache_serialized = CachingTeamSerializer(cached_team).data

                inconsistent_fields.clear()
                db_values.clear()
                cache_values.clear()

                for key in db_serialized:
                    if db_serialized[key] != cache_serialized.get(key):
                        inconsistent_fields.append(key)
                        db_values[key] = db_serialized[key]
                        cache_values[key] = cache_serialized.get(key)

                        # Track total inconsistencies by field
                        inconsistency_counts[key] = inconsistency_counts.get(key, 0) + 1

                if inconsistent_fields:
                    team_info = {
                        "team_id": team.id,
                        "team_name": team.name,
                        "inconsistent_fields": inconsistent_fields.copy(),
                        "db_values": db_values.copy(),
                        "cache_values": cache_values.copy(),
                    }
                    inconsistent_teams.append(team_info)
    else:
        # Count all teams
        total_teams = Team.objects.count()
        print(f"Checking cache consistency for all {total_teams} teams...")  # noqa: T201

        # Process all teams in batches using Django's pagination
        offset = 0
        while True:
            teams_batch = Team.objects.all().order_by("id")[offset : offset + batch_size]

            # Exit loop if no more teams
            if not teams_batch:
                break

            for team in teams_batch:
                teams_checked += 1

                # Print progress every 500 teams
                if teams_checked % 500 == 0 or teams_checked == total_teams:
                    progress_pct = (teams_checked / total_teams) * 100 if total_teams > 0 else 0
                    print(f"Progress: {teams_checked}/{total_teams} teams checked ({progress_pct:.1f}%)")  # noqa: T201

                # Get team from cache
                cached_team = get_team_in_cache(team.api_token)

                # Skip teams not in cache
                if not cached_team:
                    continue

                teams_in_cache += 1

                # Check for inconsistencies across all fields
                db_serialized = CachingTeamSerializer(team).data
                cache_serialized = CachingTeamSerializer(cached_team).data

                inconsistent_fields.clear()
                db_values.clear()
                cache_values.clear()

                for key in db_serialized:
                    if db_serialized[key] != cache_serialized.get(key):
                        inconsistent_fields.append(key)
                        db_values[key] = db_serialized[key]
                        cache_values[key] = cache_serialized.get(key)

                        # Track total inconsistencies by field
                        inconsistency_counts[key] = inconsistency_counts.get(key, 0) + 1

                if inconsistent_fields:
                    team_info = {
                        "team_id": team.id,
                        "team_name": team.name,
                        "inconsistent_fields": inconsistent_fields.copy(),
                        "db_values": db_values.copy(),
                        "cache_values": cache_values.copy(),
                    }
                    inconsistent_teams.append(team_info)

            # Move to next batch
            offset += batch_size

    # Print summary
    print("\nSummary:")  # noqa: T201
    print(f"Teams checked: {teams_checked}")  # noqa: T201
    print(f"Teams in cache: {teams_in_cache}")  # noqa: T201
    print(f"Teams with inconsistencies: {len(inconsistent_teams)}")  # noqa: T201

    # Print inconsistency breakdown by field
    if inconsistency_counts:
        print("\nInconsistencies by field:")  # noqa: T201
        for field, count in sorted(inconsistency_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  - {field}: {count} teams")  # noqa: T201

    # Print the first 10 inconsistent teams as a preview
    if inconsistent_teams:
        print("\nFirst 10 inconsistent teams:")  # noqa: T201
        for idx, team_info in enumerate(inconsistent_teams[:10]):
            print(f"{idx+1}. Team {team_info['team_id']} ({team_info['team_name']})")  # noqa: T201
            for field in team_info["inconsistent_fields"]:
                print(f"   - {field}: DB={team_info['db_values'][field]}, Cache={team_info['cache_values'][field]}")  # noqa: T201

    return inconsistent_teams


def fix_all_teams_cache_consistency(batch_size: int = 100, only_active_surveys: bool = True) -> dict[str, Any]:
    """
    Find and fix all teams with cache inconsistencies.
    Args:
        batch_size: Number of teams to process in each batch.
        only_active_surveys: If True, only check teams with active surveys.
    Returns:
        Dict with statistics about the fixed teams
    """
    # First find all teams with inconsistencies
    inconsistent_teams = find_teams_with_cache_inconsistencies(batch_size, only_active_surveys)

    if not inconsistent_teams:
        print("No inconsistencies found.")  # noqa: T201
        return {"teams_fixed": 0, "total_inconsistencies": 0, "field_fixes": {}}

    # Ask for confirmation before fixing
    confirmation = input(f"\nFound {len(inconsistent_teams)} teams with inconsistencies. Fix them? (y/n): ")

    if confirmation.lower() != "y":
        print("Operation canceled.")  # noqa: T201
        return {"teams_fixed": 0, "total_inconsistencies": len(inconsistent_teams), "field_fixes": {}}

    # Track fixes by field
    field_fixes: dict[str, int] = {}
    for team_info in inconsistent_teams:
        for field in team_info["inconsistent_fields"]:
            field_fixes[field] = field_fixes.get(field, 0) + 1

    # Fix the inconsistencies
    fixed_count = 0
    for team_info in inconsistent_teams:
        try:
            team = Team.objects.get(id=team_info["team_id"])
            set_team_in_cache(team.api_token, team)
            fixed_count += 1

            # Print progress every 10 teams
            if fixed_count % 10 == 0:
                print(f"Fixed {fixed_count}/{len(inconsistent_teams)} teams...")  # noqa: T201
        except Exception as e:
            print(f"Error fixing team {team_info['team_id']}: {str(e)}")  # noqa: T201

    print(f"\nFixed {fixed_count} out of {len(inconsistent_teams)} teams with inconsistencies.")  # noqa: T201

    # Print breakdown of fixes by field
    print("\nFields fixed:")  # noqa: T201
    for field, count in sorted(field_fixes.items(), key=lambda x: x[1], reverse=True):
        print(f"  - {field}: {count} teams")  # noqa: T201

    return {"teams_fixed": fixed_count, "total_inconsistencies": len(inconsistent_teams), "field_fixes": field_fixes}
