"""
Management command to directly create a test notification in the database.

This bypasses the Kafka pipeline for quick testing.

Usage:
    python manage.py create_test_notification --user-email test@test.com --team-id 1
"""

import random
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from posthog.models import Notification, Team, User


class Command(BaseCommand):
    help = "Create a test notification directly in the database for a specific user"

    def add_arguments(self, parser):
        parser.add_argument(
            "--user-email",
            type=str,
            required=True,
            help="Email of the user to create notification for",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="Team ID for the notification",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        user_email = options["user_email"]
        team_id = options["team_id"]

        # Validate user exists
        try:
            user = User.objects.get(email=user_email)
        except User.DoesNotExist:
            raise CommandError(f"User with email {user_email} does not exist")

        # Validate team exists
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team with id {team_id} does not exist")

        # 10 realistic notification scenarios for quick testing
        scenarios = [
            {
                "resource_type": "feature_flag",
                "title": "Feature flag enabled",
                "message": "The 'new-checkout-flow' feature flag has been enabled in production",
                "priority": "normal",
                "context": {"flag_key": "new-checkout-flow", "action": "enabled"},
            },
            {
                "resource_type": "feature_flag",
                "title": "Emergency rollback",
                "message": "Feature flag 'payment-gateway-v2' was emergency rolled back to 0%",
                "priority": "urgent",
                "context": {"flag_key": "payment-gateway-v2", "action": "emergency_rollback"},
            },
            {
                "resource_type": "insight",
                "title": "Dashboard updated",
                "message": "Your 'Product Metrics' dashboard has been updated with new insights",
                "priority": "low",
                "context": {"dashboard_name": "Product Metrics"},
            },
            {
                "resource_type": "experiment",
                "title": "Experiment results ready",
                "message": "A/B test 'Checkout Button Color' has reached statistical significance",
                "priority": "high",
                "context": {"experiment_name": "Checkout Button Color", "significance": 0.95},
            },
            {
                "resource_type": "alert",
                "title": "High error rate detected",
                "message": "Error rate exceeded 5% threshold in the last hour",
                "priority": "urgent",
                "context": {"metric": "error_rate", "threshold": 5, "current": 7.2},
            },
            {
                "resource_type": "data_warehouse",
                "title": "Data sync completed",
                "message": "Stripe data warehouse sync finished successfully",
                "priority": "low",
                "context": {"source": "Stripe", "records": 15234},
            },
            {
                "resource_type": "batch_export",
                "title": "Export failed",
                "message": "BigQuery export failed: Quota exceeded",
                "priority": "high",
                "context": {"destination": "BigQuery", "error": "Quota exceeded"},
            },
            {
                "resource_type": "feature_flag",
                "title": "Gradual rollout started",
                "message": "Feature flag 'mobile-app-redesign' rollout started at 10%",
                "priority": "normal",
                "context": {"flag_key": "mobile-app-redesign", "rollout": 10},
            },
            {
                "resource_type": "insight",
                "title": "Anomaly detected",
                "message": "Unusual pattern detected in 'Daily Active Users' metric",
                "priority": "high",
                "context": {"insight_name": "Daily Active Users", "anomaly_score": 0.89},
            },
            {
                "resource_type": "alert",
                "title": "Traffic spike detected",
                "message": "Page views increased by 300% in the last 15 minutes",
                "priority": "high",
                "context": {"metric": "pageviews", "increase": 300},
            },
        ]

        # Pick a random scenario
        scenario = random.choice(scenarios)

        # Create notification directly in database
        notification = Notification.objects.create(
            user=user,
            team=team,
            resource_type=scenario["resource_type"],
            resource_id=None,
            title=scenario["title"],
            message=scenario["message"],
            context=scenario["context"],
            priority=scenario["priority"],
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"✓ Created notification #{notification.id} for {user.email} on team {team.id} ({team.name})\n"
                f"  Title: {scenario['title']}\n"
                f"  Type: {scenario['resource_type']}\n"
                f"  Priority: {scenario['priority']}\n"
                f"  Created at: {notification.created_at}"
            )
        )
