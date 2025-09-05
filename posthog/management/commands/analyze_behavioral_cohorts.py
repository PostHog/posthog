import json
import time
import logging
from typing import Any

from django.core.management.base import BaseCommand

import structlog

from posthog.clickhouse.client.execute import sync_execute

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Generate cohort membership data (team_id, person_id, cohort_id) for persons who match behavioral cohort conditions"

    def add_arguments(self, parser):
        parser.add_argument(
            "--min-matches",
            type=int,
            default=3,
            help="Minimum number of matches required (default: 3)",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Number of days to look back (default: 30)",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            help="Optional: Filter to a specific team ID",
        )
        parser.add_argument(
            "--cohort-id",
            type=int,
            help="Optional: Filter to a specific cohort/action ID",
        )
        parser.add_argument(
            "--condition",
            type=str,
            help="Optional: Filter to a specific condition hash",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Optional: Limit the number of conditions to process",
        )

    def handle(self, *args, **options):
        min_matches = options["min_matches"]
        days = options["days"]
        team_id = options.get("team_id")
        cohort_id = options.get("cohort_id")
        condition = options.get("condition")
        limit = options.get("limit")

        logger.info("Starting cohort membership generation")

        # Step 1: Get unique condition hashes (with limit applied at query level)
        condition_hashes = self.get_unique_conditions(team_id, cohort_id, condition, days, limit)

        if not condition_hashes:
            logger.warning("No conditions found matching the criteria")
            return

        logger.info(f"Processing {len(condition_hashes)} conditions")

        # Step 2: Get cohort memberships (team_id, person_id, cohort_id)
        start_time = time.time()
        memberships = self.get_cohort_memberships(
            condition_hashes,
            min_matches,
            days,
        )

        logger.info(
            "Completed",
            total_memberships=len(memberships),
            conditions_processed=len(condition_hashes),
            total_time_seconds=round(time.time() - start_time, 2),
        )

        self.stdout.write("team_id,person_id,cohort_id")

        display_limit = 5
        for team_id, person_id, cohort_id in memberships[:display_limit]:
            self.stdout.write(f"{team_id},{person_id},{cohort_id}")

        if len(memberships) > display_limit:
            self.stdout.write(f"\n... showing first {display_limit} of {len(memberships)} total memberships ...")

    def get_unique_conditions(
        self,
        team_id: int | None,
        cohort_id: int | None,
        condition: str | None,
        days: int,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get unique condition hashes from ClickHouse with optional limit"""

        # Basic validation for reasonable bounds
        if not isinstance(days, int) or days < 0 or days > 365:
            raise ValueError(f"Invalid days value: {days}")
        if limit is not None and (not isinstance(limit, int) or limit < 1 or limit > 100000):
            raise ValueError(f"Invalid limit value: {limit}")

        where_clauses = ["date >= now() - toIntervalDay(%(days)s)"]
        params: dict[str, Any] = {"days": days}

        if team_id:
            where_clauses.append("team_id = %(team_id)s")
            params["team_id"] = team_id
        if cohort_id:
            where_clauses.append("cohort_id = %(cohort_id)s")
            params["cohort_id"] = cohort_id
        if condition:
            where_clauses.append("condition = %(condition)s")
            params["condition"] = condition

        where_clause = " AND ".join(where_clauses)

        # Add LIMIT clause if specified
        limit_clause = f"LIMIT {int(limit)}" if limit else ""

        query = f"""
            SELECT DISTINCT
                team_id,
                cohort_id,
                condition
            FROM behavioral_cohorts_matches
            WHERE {where_clause}
            ORDER BY team_id, cohort_id, condition
            {limit_clause}
        """

        try:
            results = sync_execute(query, params)
            return [
                {
                    "team_id": row[0],
                    "cohort_id": row[1],
                    "condition": row[2],
                }
                for row in results
            ]
        except Exception as e:
            logger.exception("Error fetching unique conditions", error=str(e))
            raise

    def get_cohort_memberships(
        self,
        condition_hashes: list[dict[str, Any]],
        min_matches: int,
        days: int,
    ) -> list[tuple[int, str, int]]:
        """Get all cohort memberships (team_id, person_id, cohort_id) for persons with minimum matches"""

        # Basic validation for reasonable bounds
        if not isinstance(days, int) or days < 0 or days > 365:
            raise ValueError(f"Invalid days value: {days}")
        if not isinstance(min_matches, int) or min_matches < 0:
            raise ValueError(f"Invalid min_matches value: {min_matches}")

        memberships = []
        total_conditions = len(condition_hashes)

        for idx, condition_data in enumerate(condition_hashes, 1):
            team_id = condition_data["team_id"]
            cohort_id = condition_data["cohort_id"]
            condition_hash = condition_data["condition"]

            # Only log every 100th condition to avoid spam
            if idx % 500 == 0 or idx == total_conditions:
                logger.info(f"Progress: {idx}/{total_conditions}")
            log_comment = json.dumps(
                {
                    "source": "analyze_behavioral_cohorts",
                    "operation": "get_cohort_memberships",
                    "cohort_id": cohort_id,
                }
            )

            query = f"""
                SELECT
                    person_id
                FROM behavioral_cohorts_matches
                WHERE
                    team_id = %(team_id)s
                    AND cohort_id = %(cohort_id)s
                    AND condition = %(condition)s
                    AND date >= now() - toIntervalDay(%(days)s)
                    AND matches >= %(min_matches)s
                LIMIT 100000
                SETTINGS log_comment = '{log_comment}'
            """

            try:
                results = sync_execute(
                    query,
                    {
                        "team_id": team_id,
                        "cohort_id": cohort_id,
                        "condition": condition_hash,
                        "days": days,
                        "min_matches": min_matches,
                    },
                )

                for row in results:
                    person_id = row[0]
                    memberships.append((team_id, person_id, cohort_id))

            except Exception as e:
                logger.exception("Error processing condition", condition=condition_hash[:16] + "...", error=str(e))
                continue

        return memberships
