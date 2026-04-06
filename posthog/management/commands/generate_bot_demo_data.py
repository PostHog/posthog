import random
from datetime import timedelta
from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from posthog.hogql.functions.bot_ua_fixtures import BOT_USER_AGENTS

from posthog.demo.products.hedgebox.taxonomy import (
    SITE_URL,
    URL_FILES,
    URL_HOME,
    URL_LOGIN,
    URL_MARIUS_TECH_TIPS,
    URL_PRICING,
    URL_SIGNUP,
)
from posthog.models import Team
from posthog.models.event.util import create_event

# Crawl patterns per bot category - bots visit different pages based on their purpose
CRAWL_PATTERNS: dict[str, list[str]] = {
    "ai_agent": [
        URL_HOME,
        URL_MARIUS_TECH_TIPS,
        URL_PRICING,
        f"{SITE_URL}/docs/",
        f"{SITE_URL}/blog/",
    ],
    "search_crawler": [
        URL_HOME,
        URL_PRICING,
        URL_MARIUS_TECH_TIPS,
        URL_FILES,
        f"{SITE_URL}/sitemap.xml",
        f"{SITE_URL}/robots.txt",
    ],
    "seo_crawler": [
        f"{SITE_URL}/sitemap.xml",
        f"{SITE_URL}/robots.txt",
        URL_HOME,
        URL_PRICING,
    ],
    "social_crawler": [
        # Social bots fetch link previews for shared content
        f"{SITE_URL}/files/shared-abc123/",
        f"{SITE_URL}/files/shared-def456/",
        URL_MARIUS_TECH_TIPS,
        URL_HOME,
    ],
    "monitoring": [
        f"{SITE_URL}/api/v1/health",
        f"{SITE_URL}/api/v1/status",
        URL_HOME,
    ],
    "http_client": [
        f"{SITE_URL}/api/v1/files",
        f"{SITE_URL}/api/v1/users",
        URL_HOME,
    ],
    "headless_browser": [
        URL_HOME,
        URL_SIGNUP,
        URL_LOGIN,
        URL_PRICING,
        URL_FILES,
    ],
    "regular_browser": [
        URL_HOME,
        URL_PRICING,
        URL_SIGNUP,
        URL_LOGIN,
        URL_FILES,
        URL_MARIUS_TECH_TIPS,
    ],
}

# Referrers for social crawlers (the platform where the link was shared)
SOCIAL_REFERRERS = [
    "https://twitter.com/",
    "https://x.com/",
    "https://www.facebook.com/",
    "https://www.linkedin.com/feed/",
    "https://slack.com/",
    "https://discord.com/channels/",
    "https://www.reddit.com/r/technology/",
    "https://news.ycombinator.com/",
]

DATACENTER_GEOIP = [
    {
        "$geoip_country_code": "US",
        "$geoip_city_name": "Ashburn",
        "$geoip_region_name": "Virginia",
    },  # AWS us-east-1
    {
        "$geoip_country_code": "US",
        "$geoip_city_name": "San Jose",
        "$geoip_region_name": "California",
    },  # Google Cloud
    {
        "$geoip_country_code": "US",
        "$geoip_city_name": "Seattle",
        "$geoip_region_name": "Washington",
    },  # Azure West US
    {
        "$geoip_country_code": "IE",
        "$geoip_city_name": "Dublin",
        "$geoip_region_name": "Dublin",
    },  # AWS eu-west-1
    {
        "$geoip_country_code": "DE",
        "$geoip_city_name": "Frankfurt",
        "$geoip_region_name": "Hesse",
    },  # AWS eu-central-1
    {
        "$geoip_country_code": "SG",
        "$geoip_city_name": "Singapore",
        "$geoip_region_name": "Singapore",
    },  # AWS ap-southeast-1
    {
        "$geoip_country_code": "JP",
        "$geoip_city_name": "Tokyo",
        "$geoip_region_name": "Tokyo",
    },  # AWS ap-northeast-1
]


class Command(BaseCommand):
    help = "Generate demo events with bot/automation user agents for testing traffic classification"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="Team ID to generate events for")
        parser.add_argument(
            "--count",
            type=int,
            default=10,
            help="Number of events per user agent type (default: 10)",
        )
        parser.add_argument(
            "--days-back",
            type=int,
            default=7,
            help="Spread events over this many days (default: 7)",
        )

    def handle(self, *args, **options):
        team_id = options["team_id"]
        count_per_type = options["count"]
        days_back = options["days_back"]

        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team with ID {team_id} does not exist")

        self.stdout.write(f"Generating bot demo data for team {team_id} ({team.name})...")

        now = timezone.now()
        total_events = 0

        for category, user_agents in BOT_USER_AGENTS.items():
            urls = CRAWL_PATTERNS.get(category, [URL_HOME])

            for user_agent in user_agents:
                for _ in range(count_per_type):
                    timestamp = now - timedelta(
                        days=random.uniform(0, days_back),
                        hours=random.uniform(0, 24),
                    )
                    distinct_id = f"bot-demo-{category}-{uuid4().hex[:8]}"
                    event_uuid = uuid4()
                    current_url = random.choice(urls)

                    properties: dict = {
                        "$user_agent": user_agent,
                        "$current_url": current_url,
                        "$lib": "bot-demo-generator",
                        "$host": "hedgebox.net",
                        "bot_category": category,
                    }

                    # Social crawlers have referrers (they're fetching link previews)
                    if category == "social_crawler":
                        properties["$referrer"] = random.choice(SOCIAL_REFERRERS)

                    # Add datacenter GeoIP for bot traffic
                    geoip = random.choice(DATACENTER_GEOIP)
                    properties.update(geoip)

                    create_event(
                        event_uuid=event_uuid,
                        event="$pageview",
                        team=team,
                        distinct_id=distinct_id,
                        timestamp=timestamp,
                        properties=properties,
                    )
                    total_events += 1

            self.stdout.write(f"  Generated {count_per_type * len(user_agents)} events for {category}")

        self.stdout.write(self.style.SUCCESS(f"\nGenerated {total_events} total events"))
        self.stdout.write("\nTo verify, run these queries in the SQL editor:")
        self.stdout.write(
            """
SELECT __preview_getTrafficType(properties.$user_agent) as traffic_type, count()
FROM events
WHERE properties.$lib = 'bot-demo-generator'
GROUP BY traffic_type
ORDER BY count() DESC

SELECT __preview_getTrafficCategory(properties.$user_agent) as category, count()
FROM events
WHERE properties.$lib = 'bot-demo-generator'
GROUP BY category
ORDER BY count() DESC
"""
        )
