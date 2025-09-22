import time
import asyncio
import logging
from typing import Any

from django.core.management.base import BaseCommand

import structlog
from temporalio.common import WorkflowIDReusePolicy

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.constants import MESSAGING_TASK_QUEUE
from posthog.temporal.common.client import async_connect
from posthog.temporal.messaging.behavioral_cohorts_workflow import BehavioralCohortsWorkflowInputs

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
        parser.add_argument(
            "--parallelism",
            type=int,
            default=10,
            help="Number of parallel workers for processing (default: 10)",
        )
        parser.add_argument(
            "--use-temporal",
            action="store_true",
            default=True,
            help="Use Temporal workflow for parallel processing (default: True)",
        )
        parser.add_argument(
            "--no-temporal",
            dest="use_temporal",
            action="store_false",
            help="Disable Temporal workflow and use sequential processing",
        )

    def handle(self, *args, **options):
        min_matches = options["min_matches"]
        days = options["days"]
        team_id = options.get("team_id")
        cohort_id = options.get("cohort_id")
        condition = options.get("condition")
        limit = options.get("limit")
        parallelism = options.get("parallelism", 10)
        use_temporal = options.get("use_temporal", True)

        logger.info(
            "Starting cohort membership generation",
            use_temporal=use_temporal,
            parallelism=parallelism if use_temporal else 1,
        )

        if use_temporal:
            # Use Temporal workflow for parallel processing
            start_time = time.time()
            result = self.run_temporal_workflow(
                team_id=team_id,
                cohort_id=cohort_id,
                condition=condition,
                min_matches=min_matches,
                days=days,
                limit=limit,
                parallelism=parallelism,
            )

            if result:
                total_time_seconds = round(time.time() - start_time, 2)

                logger.info(
                    "Completed (Temporal parallel processing)",
                    total_memberships=result["total_memberships"],
                    conditions_processed=result["conditions_processed"],
                    batches_processed=result["batches_processed"],
                    parallelism=parallelism,
                    total_time_seconds=total_time_seconds,
                )

                self.stdout.write(
                    f"Workflow completed: {result['total_memberships']} memberships from {result['conditions_processed']} conditions"
                )
                self.stdout.write(
                    f"Processed in {result['batches_processed']} parallel batches (parallelism={parallelism})"
                )
                self.stdout.write(f"Total time: {total_time_seconds} seconds")

                # Display sample results
                if result.get("memberships"):
                    self.stdout.write("\nSample results (first 5):")
                    self.stdout.write("team_id,person_id,cohort_id")
                    for team_id, person_id, cohort_id in result["memberships"][:5]:
                        self.stdout.write(f"{team_id},{person_id},{cohort_id}")

                    if len(result["memberships"]) > 5:
                        self.stdout.write(
                            f"\n... showing first 5 of {result['total_memberships']} total memberships ..."
                        )
        else:
            # Legacy sequential processing
            logger.info("Using legacy sequential processing")

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

    def run_temporal_workflow(
        self,
        team_id: int | None,
        cohort_id: int | None,
        condition: str | None,
        min_matches: int,
        days: int,
        limit: int | None,
        parallelism: int,
    ) -> dict[str, Any] | None:
        """Run the Temporal workflow for parallel processing."""

        async def _run_workflow():
            # Connect to Temporal
            client = await async_connect()

            # Create workflow inputs
            inputs = BehavioralCohortsWorkflowInputs(
                team_id=team_id,
                cohort_id=cohort_id,
                condition=condition,
                min_matches=min_matches,
                days=days,
                limit=limit,
                parallelism=parallelism,
            )

            # Generate unique workflow ID
            workflow_id = f"behavioral-cohorts-{team_id or 'all'}-{cohort_id or 'all'}-{int(time.time())}"

            logger.info(f"Starting Temporal workflow: {workflow_id}")

            try:
                # Execute the workflow
                result = await client.execute_workflow(
                    "behavioral-cohorts-analysis",
                    inputs,
                    id=workflow_id,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                    task_queue=MESSAGING_TASK_QUEUE,
                )

                logger.info(f"Workflow {workflow_id} completed successfully")
                return result

            except Exception as e:
                logger.exception(f"Workflow execution failed: {e}")
                raise

        try:
            # Run the async function
            result = asyncio.run(_run_workflow())
            return result
        except Exception as e:
            logger.exception(f"Failed to execute Temporal workflow: {e}")
            return None

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
            with tags_context(
                team_id=team_id,
                feature=Feature.BEHAVIORAL_COHORTS,
                cohort_id=cohort_id,
                product=Product.MESSAGING,
                query_type="get_unique_conditions",
            ):
                results = sync_execute(query, params, ch_user=ClickHouseUser.COHORTS, workload=Workload.OFFLINE)
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

            query = """
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
            """

            try:
                with tags_context(
                    team_id=team_id,
                    feature=Feature.BEHAVIORAL_COHORTS,
                    cohort_id=cohort_id,
                    product=Product.MESSAGING,
                    query_type="get_cohort_memberships",
                ):
                    results = sync_execute(
                        query,
                        {
                            "team_id": team_id,
                            "cohort_id": cohort_id,
                            "condition": condition_hash,
                            "days": days,
                            "min_matches": min_matches,
                        },
                        ch_user=ClickHouseUser.COHORTS,
                        workload=Workload.OFFLINE,
                    )

                for row in results:
                    person_id = row[0]
                    memberships.append((team_id, person_id, cohort_id))

            except Exception as e:
                logger.exception("Error processing condition", condition=condition_hash[:16] + "...", error=str(e))
                continue

        return memberships
