"""
Management command to fire a test notification with realistic random data.

Broadcasts notification to entire team - preference filter will fan out to subscribed users.

Usage:
    python manage.py fire_test_notification --team-id 1
"""

import random
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from posthog.models import Team
from posthog.notifications.producer import NotificationEvent, produce_notification_event


class Command(BaseCommand):
    help = "Broadcast a test notification with randomly chosen realistic data to a team"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="Team ID to broadcast the notification to",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_id = options["team_id"]

        # Validate team exists
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team with id {team_id} does not exist")

        # 50 realistic notification scenarios
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
                "title": "Feature flag rollout complete",
                "message": "Feature flag 'beta-features' is now at 100% rollout",
                "priority": "low",
                "context": {"flag_key": "beta-features", "rollout": 100},
            },
            {
                "resource_type": "feature_flag",
                "title": "Feature flag deleted",
                "message": "The 'old-navigation' feature flag was permanently deleted",
                "priority": "normal",
                "context": {"flag_key": "old-navigation", "action": "deleted"},
            },
            {
                "resource_type": "insight",
                "title": "Dashboard updated",
                "message": "Your 'Product Metrics' dashboard has been updated with new insights",
                "priority": "low",
                "context": {"dashboard_name": "Product Metrics"},
            },
            {
                "resource_type": "insight",
                "title": "Insight calculation complete",
                "message": "The 'User Retention' insight has finished calculating",
                "priority": "normal",
                "context": {"insight_name": "User Retention"},
            },
            {
                "resource_type": "experiment",
                "title": "Experiment results ready",
                "message": "A/B test 'Checkout Button Color' has reached statistical significance",
                "priority": "high",
                "context": {"experiment_name": "Checkout Button Color", "significance": 0.95},
            },
            {
                "resource_type": "experiment",
                "title": "Experiment launched",
                "message": "New experiment 'Homepage Hero Test' is now live",
                "priority": "normal",
                "context": {"experiment_name": "Homepage Hero Test"},
            },
            {
                "resource_type": "experiment",
                "title": "Experiment ended",
                "message": "Experiment 'Pricing Page Redesign' has been stopped",
                "priority": "normal",
                "context": {"experiment_name": "Pricing Page Redesign"},
            },
            {
                "resource_type": "alert",
                "title": "High error rate detected",
                "message": "Error rate exceeded 5% threshold in the last hour",
                "priority": "urgent",
                "context": {"metric": "error_rate", "threshold": 5, "current": 7.2},
            },
            {
                "resource_type": "alert",
                "title": "Traffic spike detected",
                "message": "Page views increased by 300% in the last 15 minutes",
                "priority": "high",
                "context": {"metric": "pageviews", "increase": 300},
            },
            {
                "resource_type": "alert",
                "title": "Conversion rate dropped",
                "message": "Checkout conversion rate fell below 2% threshold",
                "priority": "high",
                "context": {"metric": "conversion_rate", "threshold": 2, "current": 1.4},
            },
            {
                "resource_type": "data_warehouse",
                "title": "Data sync completed",
                "message": "Stripe data warehouse sync finished successfully",
                "priority": "low",
                "context": {"source": "Stripe", "records": 15234},
            },
            {
                "resource_type": "data_warehouse",
                "title": "Data sync failed",
                "message": "Salesforce sync failed: Authentication error",
                "priority": "high",
                "context": {"source": "Salesforce", "error": "Authentication error"},
            },
            {
                "resource_type": "data_warehouse",
                "title": "New data source connected",
                "message": "HubSpot has been successfully connected to your data warehouse",
                "priority": "normal",
                "context": {"source": "HubSpot"},
            },
            {
                "resource_type": "batch_export",
                "title": "Export completed",
                "message": "Daily S3 export completed successfully (1.2M events)",
                "priority": "low",
                "context": {"destination": "S3", "events": 1200000},
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
                "title": "Feature flag conflict detected",
                "message": "Multiple flags targeting the same users may cause conflicts",
                "priority": "normal",
                "context": {"flags": ["test-a", "test-b"]},
            },
            {
                "resource_type": "insight",
                "title": "Anomaly detected",
                "message": "Unusual pattern detected in 'Daily Active Users' metric",
                "priority": "high",
                "context": {"insight_name": "Daily Active Users", "anomaly_score": 0.89},
            },
            {
                "resource_type": "experiment",
                "title": "Sample size reached",
                "message": "Experiment 'Email Subject Line' has reached target sample size",
                "priority": "normal",
                "context": {"experiment_name": "Email Subject Line", "sample_size": 10000},
            },
            {
                "resource_type": "alert",
                "title": "Alert threshold updated",
                "message": "Error rate alert threshold changed from 3% to 5%",
                "priority": "low",
                "context": {"alert": "error_rate", "old_threshold": 3, "new_threshold": 5},
            },
            {
                "resource_type": "feature_flag",
                "title": "Gradual rollout started",
                "message": "Feature flag 'mobile-app-redesign' rollout started at 10%",
                "priority": "normal",
                "context": {"flag_key": "mobile-app-redesign", "rollout": 10},
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
                "title": "Shared with you",
                "message": "Alice shared the 'Q4 Revenue Analysis' dashboard with you",
                "priority": "normal",
                "context": {"dashboard_name": "Q4 Revenue Analysis", "shared_by": "Alice"},
            },
            {
                "resource_type": "experiment",
                "title": "Variant performing poorly",
                "message": "Variant B in 'Onboarding Flow' is underperforming by 25%",
                "priority": "high",
                "context": {"experiment_name": "Onboarding Flow", "variant": "B", "performance": -25},
            },
            {
                "resource_type": "data_warehouse",
                "title": "Schema change detected",
                "message": "New columns detected in Postgres table 'users'",
                "priority": "normal",
                "context": {"source": "Postgres", "table": "users", "new_columns": 3},
            },
            {
                "resource_type": "alert",
                "title": "API latency high",
                "message": "Average API response time exceeded 500ms threshold",
                "priority": "urgent",
                "context": {"metric": "api_latency", "threshold": 500, "current": 782},
            },
            {
                "resource_type": "batch_export",
                "title": "Export schedule changed",
                "message": "Snowflake export schedule updated to run every 6 hours",
                "priority": "low",
                "context": {"destination": "Snowflake", "schedule": "6h"},
            },
            {
                "resource_type": "feature_flag",
                "title": "User override added",
                "message": "Manual override added for user@example.com on 'premium-features'",
                "priority": "low",
                "context": {"flag_key": "premium-features", "user": "user@example.com"},
            },
            {
                "resource_type": "insight",
                "title": "Scheduled refresh failed",
                "message": "Failed to refresh 'Monthly Trends' dashboard",
                "priority": "normal",
                "context": {"dashboard_name": "Monthly Trends", "error": "Timeout"},
            },
            {
                "resource_type": "experiment",
                "title": "Control group contaminated",
                "message": "Users in control group may have been exposed to treatment",
                "priority": "high",
                "context": {"experiment_name": "Pricing Test", "contamination_rate": 0.12},
            },
            {
                "resource_type": "alert",
                "title": "Mobile crash rate spike",
                "message": "iOS app crash rate increased to 2.5% (normal: 0.3%)",
                "priority": "urgent",
                "context": {"platform": "iOS", "crash_rate": 2.5, "baseline": 0.3},
            },
            {
                "resource_type": "data_warehouse",
                "title": "Daily sync running late",
                "message": "Zendesk sync is 3 hours behind schedule",
                "priority": "normal",
                "context": {"source": "Zendesk", "delay_hours": 3},
            },
            {
                "resource_type": "feature_flag",
                "title": "Cohort targeting updated",
                "message": "Feature flag 'beta-access' now targets 'Power Users' cohort",
                "priority": "normal",
                "context": {"flag_key": "beta-access", "cohort": "Power Users"},
            },
            {
                "resource_type": "insight",
                "title": "Funnel drop-off alert",
                "message": "50% drop-off detected at step 2 of signup funnel",
                "priority": "high",
                "context": {"funnel": "Signup", "step": 2, "drop_off": 50},
            },
            {
                "resource_type": "experiment",
                "title": "Winner declared",
                "message": "Variant A declared winner in 'Landing Page Test' with 95% confidence",
                "priority": "high",
                "context": {"experiment_name": "Landing Page Test", "winner": "A", "confidence": 0.95},
            },
            {
                "resource_type": "batch_export",
                "title": "Destination unreachable",
                "message": "Cannot connect to Redshift cluster for export",
                "priority": "urgent",
                "context": {"destination": "Redshift", "error": "Connection timeout"},
            },
            {
                "resource_type": "alert",
                "title": "Session duration increased",
                "message": "Average session duration up 45% - possible tracking issue",
                "priority": "normal",
                "context": {"metric": "session_duration", "change": 45},
            },
            {
                "resource_type": "data_warehouse",
                "title": "Query optimization needed",
                "message": "Database query taking >30s to complete",
                "priority": "normal",
                "context": {"query": "user_events_aggregation", "duration": 34},
            },
            {
                "resource_type": "feature_flag",
                "title": "Dependency conflict",
                "message": "Feature flag 'new-ui' requires 'react-18' flag to be enabled",
                "priority": "high",
                "context": {"flag_key": "new-ui", "dependency": "react-18"},
            },
            {
                "resource_type": "insight",
                "title": "Report generated",
                "message": "Your weekly product metrics report is ready",
                "priority": "low",
                "context": {"report_type": "weekly", "period": "2024-W01"},
            },
            {
                "resource_type": "experiment",
                "title": "Traffic allocation changed",
                "message": "Experiment traffic split updated to 50/50 from 80/20",
                "priority": "normal",
                "context": {"experiment_name": "CTA Button Test", "old_split": "80/20", "new_split": "50/50"},
            },
            {
                "resource_type": "alert",
                "title": "Unusual user behavior",
                "message": "Bot traffic detected - 1000+ signups from same IP",
                "priority": "urgent",
                "context": {"metric": "signups", "count": 1234, "ip": "192.168.1.1"},
            },
            {
                "resource_type": "data_warehouse",
                "title": "Data quality issue",
                "message": "15% of records missing required fields in latest sync",
                "priority": "high",
                "context": {"source": "Intercom", "missing_fields": 15},
            },
            {
                "resource_type": "batch_export",
                "title": "Export backlog cleared",
                "message": "All pending exports to GCS have been processed",
                "priority": "low",
                "context": {"destination": "GCS", "backlog_size": 0},
            },
            {
                "resource_type": "feature_flag",
                "title": "Scheduled rollout complete",
                "message": "Scheduled rollout for 'dark-mode' reached 100% as planned",
                "priority": "normal",
                "context": {"flag_key": "dark-mode", "rollout": 100},
            },
            {
                "resource_type": "insight",
                "title": "Retention milestone",
                "message": "7-day retention reached 60% - highest this quarter!",
                "priority": "normal",
                "context": {"metric": "retention_7d", "value": 60, "milestone": "quarterly_high"},
            },
            {
                "resource_type": "experiment",
                "title": "Segment performance",
                "message": "Mobile users show 2x better conversion in variant B",
                "priority": "high",
                "context": {"experiment_name": "Checkout Flow", "segment": "mobile", "uplift": 2.0},
            },
            {
                "resource_type": "alert",
                "title": "Revenue drop detected",
                "message": "Daily revenue down 30% compared to 7-day average",
                "priority": "urgent",
                "context": {"metric": "revenue", "change": -30, "period": "7d"},
            },
            {
                "resource_type": "data_warehouse",
                "title": "Connection restored",
                "message": "Connection to MongoDB data warehouse has been restored",
                "priority": "normal",
                "context": {"source": "MongoDB", "downtime_minutes": 45},
            },
            {
                "resource_type": "feature_flag",
                "title": "Multivariate test started",
                "message": "New multivariate test with 4 variants launched for 'hero-section'",
                "priority": "normal",
                "context": {"flag_key": "hero-section", "variants": 4},
            },
        ]

        # Pick a random scenario
        scenario = random.choice(scenarios)

        # Broadcast notification to team through producer
        # The preference filter consumer will fan out to subscribed users
        event = NotificationEvent(
            team_id=team.id,
            resource_type=scenario["resource_type"],
            event_type="triggered",  # Generic event type for testing
            resource_id=None,  # Optional - could add random IDs if needed
            title=scenario["title"],
            message=scenario["message"],
            context=scenario["context"],
            priority=scenario["priority"],
        )

        produce_notification_event(event)

        self.stdout.write(
            self.style.SUCCESS(
                f"✓ Broadcast notification to team {team.id} ({team.name})\n"
                f"  Title: {scenario['title']}\n"
                f"  Type: {scenario['resource_type']}\n"
                f"  Priority: {scenario['priority']}\n"
                f"  → Will be delivered to users subscribed to '{scenario['resource_type']}' notifications"
            )
        )
