"""
Generate realistic subscription revenue events for revenue analytics.

Usage:
    ./manage.py generate_revenue_analytics_subscription_data --team-id=1
"""

from __future__ import annotations

import uuid
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from django.core.management.base import BaseCommand

import structlog
from dateutil.relativedelta import relativedelta

from posthog.api.capture import capture_internal
from posthog.models import Team

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Plan:
    name: str
    product_id: str
    monthly_price: int
    annual_price: int
    currency: str
    dropoff_days: int


def add_months(timestamp: datetime, months: int) -> datetime:
    return timestamp + relativedelta(months=months)


def add_years(timestamp: datetime, years: int) -> datetime:
    return timestamp + relativedelta(years=years)


class Command(BaseCommand):
    help = "Generate realistic subscription charge events via capture_internal"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="Team ID to create events for")
        parser.add_argument("--num-customers", type=int, default=50, help="Number of customers to generate")
        parser.add_argument("--start-date", type=str, default="2024-01-01", help="Start date (YYYY-MM-DD)")
        parser.add_argument("--months", type=int, default=12, help="Months of activity to generate")
        parser.add_argument("--event-name", type=str, default="subscription_charge", help="Event name to emit")
        parser.add_argument("--revenue-property", type=str, default="price", help="Property for revenue amount")
        parser.add_argument(
            "--subscription-property",
            type=str,
            default="subscription_id",
            help="Property for subscription identifier",
        )
        parser.add_argument("--product-property", type=str, default="product_id", help="Property for product id")
        parser.add_argument("--coupon-property", type=str, default="coupon", help="Property for coupon id")
        parser.add_argument(
            "--dropoff-days-property",
            type=str,
            default="dropoff_days",
            help="Property for subscription dropoff days",
        )
        parser.add_argument("--seed", type=int, help="Random seed for reproducibility")

    def handle(self, *args, **options):
        team_id = options["team_id"]
        num_customers = options["num_customers"]
        start_date = datetime.fromisoformat(options["start_date"]).replace(tzinfo=UTC)
        months = options["months"]
        event_name = options["event_name"]
        revenue_property = options["revenue_property"]
        subscription_property = options["subscription_property"]
        product_property = options["product_property"]
        coupon_property = options["coupon_property"]
        dropoff_days_property = options["dropoff_days_property"]
        seed = options.get("seed")

        if seed is not None:
            random.seed(seed)

        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Team with ID {team_id} does not exist!"))
            return

        plans = [
            Plan("Starter", "starter", monthly_price=29, annual_price=290, currency="USD", dropoff_days=30),
            Plan("Pro", "pro", monthly_price=79, annual_price=790, currency="USD", dropoff_days=45),
            Plan("Business", "business", monthly_price=199, annual_price=1990, currency="USD", dropoff_days=60),
        ]

        token = team.api_token
        self.stdout.write(self.style.SUCCESS(f"Seeding revenue events for team '{team.name}' (ID: {team_id})"))
        self.stdout.write(f"  Customers: {num_customers}")
        self.stdout.write(f"  Months: {months}")
        self.stdout.write(f"  Event: {event_name}")

        failures = 0
        events_sent = 0

        for customer_index in range(num_customers):
            distinct_id = f"customer_{customer_index}_{uuid.uuid4()}"
            subscription_id = f"sub_{uuid.uuid4()}"
            plan = random.choice(plans)
            is_annual = random.random() < 0.2
            churn_after = random.randint(3, months) if random.random() < 0.35 else months
            coupon = f"PROMO{random.randint(10, 40)}" if random.random() < 0.15 else None

            for period_index in range(churn_after if not is_annual else max(1, churn_after // 12)):
                timestamp = add_years(start_date, period_index) if is_annual else add_months(start_date, period_index)

                price = plan.annual_price if is_annual else plan.monthly_price
                if period_index > 0 and random.random() < 0.1:
                    price = int(price * 1.25)

                properties: dict[str, Any] = {
                    subscription_property: subscription_id,
                    product_property: plan.product_id,
                    revenue_property: price,
                    "currency": plan.currency,
                    "plan": plan.name,
                    "billing_period": "annual" if is_annual else "monthly",
                    dropoff_days_property: plan.dropoff_days,
                }
                if coupon and period_index < 2:
                    properties[coupon_property] = coupon

                try:
                    resp = capture_internal(
                        token=token,
                        event_name=event_name,
                        event_source="generate_revenue_analytics_subscription_data",
                        distinct_id=distinct_id,
                        timestamp=timestamp,
                        properties=properties,
                        process_person_profile=True,
                    )
                    resp.raise_for_status()
                    events_sent += 1
                except Exception as e:
                    failures += 1
                    logger.warning(
                        "subscription_event_failed",
                        distinct_id=distinct_id,
                        error=str(e),
                        subscription_id=subscription_id,
                    )

        self.stdout.write(self.style.SUCCESS(f"Finished. Sent {events_sent} events, failures: {failures}."))
