import random
from datetime import timedelta
from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_EVENTS_JSON
from posthog.models import Team

BOT_USER_AGENTS = {
    "ai_agent": [
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; GPTBot/1.2; +https://openai.com/gptbot",
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ClaudeBot/1.0; +https://anthropic.com",
        "Mozilla/5.0 (compatible; ChatGPT-User/1.0; +https://openai.com/bot)",
        "Mozilla/5.0 (compatible; PerplexityBot/1.0; +https://perplexity.ai/bot)",
        "Mozilla/5.0 (compatible; Google-Extended; +https://developers.google.com/search/docs/crawling-indexing/google-extended)",
        "CCBot/2.0 (https://commoncrawl.org/faq/)",
        "anthropic-ai (https://anthropic.com)",
        "cohere-ai",
        "meta-externalagent/1.1",
        "Bytespider",
    ],
    "search_crawler": [
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Mozilla/5.0 (compatible; Bingbot/2.0; +http://www.bing.com/bingbot.htm)",
        "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)",
        "Mozilla/5.0 (compatible; Baiduspider/2.0; +http://www.baidu.com/search/spider.html)",
        "DuckDuckBot/1.0; (+http://duckduckgo.com/duckduckbot.html)",
        "Mozilla/5.0 (compatible; Yahoo! Slurp; http://help.yahoo.com/help/us/ysearch/slurp)",
    ],
    "seo_crawler": [
        "Mozilla/5.0 (compatible; AhrefsBot/7.0; +http://ahrefs.com/robot/)",
        "Mozilla/5.0 (compatible; SemrushBot/7~bl; +http://www.semrush.com/bot.html)",
        "Mozilla/5.0 (compatible; MJ12bot/v1.4.8; http://mj12bot.com/)",
        "Mozilla/5.0 (compatible; DotBot/1.2; +https://opensiteexplorer.org/dotbot)",
        "Mozilla/5.0 (compatible; PetalBot; +https://webmaster.petalsearch.com/site/petalbot)",
    ],
    "social_crawler": [
        "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Twitterbot/1.0",
        "LinkedInBot/1.0 (compatible; Mozilla/5.0; Apache-HttpClient +http://www.linkedin.com)",
        "Pinterest/0.2 (+http://www.pinterest.com/)",
        "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)",
        "TelegramBot (like TwitterBot)",
        "WhatsApp/2.23.2.79 A",
    ],
    "monitoring": [
        "Pingdom.com_bot_version_1.4_(http://www.pingdom.com/)",
        "Mozilla/5.0 (compatible; UptimeRobot/2.0; http://www.uptimerobot.com/)",
        "Site24x7 (https://www.site24x7.com)",
        "Mozilla/5.0 (compatible; StatusCake)",
        "Datadog/Synthetics",
    ],
    "http_client": [
        "curl/7.88.1",
        "curl/8.1.2",
        "Wget/1.21.3",
        "python-requests/2.31.0",
        "axios/1.4.0",
        "node-fetch/3.3.1",
        "Go-http-client/1.1",
        "Java/17.0.1",
        "okhttp/4.10.0",
        "Apache-HttpClient/4.5.14 (Java/17.0.1)",
        "libwww-perl/6.67",
        "Scrapy/2.9.0 (+https://scrapy.org)",
    ],
    "headless_browser": [
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/114.0.5735.198 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) PhantomJS/2.1.1 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36 Puppeteer",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36 Playwright",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36 Selenium",
    ],
    "regular_browser": [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    ],
}

SAMPLE_URLS = [
    "https://example.com/",
    "https://example.com/pricing",
    "https://example.com/docs",
    "https://example.com/blog/how-to-get-started",
    "https://example.com/api/v1/health",
    "https://example.com/robots.txt",
    "https://example.com/sitemap.xml",
    "https://example.com/product/analytics",
]


class Command(BaseCommand):
    help = "Generate demo events with bot/automation user agents for testing traffic classification"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="Team ID to generate events for")
        parser.add_argument("--count", type=int, default=10, help="Number of events per user agent type (default: 10)")
        parser.add_argument("--days-back", type=int, default=7, help="Spread events over this many days (default: 7)")

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
        producer = ClickhouseProducer()
        total_events = 0

        for category, user_agents in BOT_USER_AGENTS.items():
            for user_agent in user_agents:
                for _ in range(count_per_type):
                    timestamp = now - timedelta(
                        days=random.uniform(0, days_back),
                        hours=random.uniform(0, 24),
                    )
                    distinct_id = f"bot-demo-{category}-{uuid4().hex[:8]}"
                    event_uuid = uuid4()

                    event_data = {
                        "uuid": str(event_uuid),
                        "event": "$pageview",
                        "properties": {
                            "$raw_user_agent": user_agent,
                            "$current_url": random.choice(SAMPLE_URLS),
                            "$lib": "bot-demo-generator",
                            "$host": "example.com",
                            "bot_category": category,
                        },
                        "timestamp": timestamp.isoformat(),
                        "team_id": team_id,
                        "distinct_id": distinct_id,
                    }

                    producer.produce(topic=KAFKA_EVENTS_JSON, data=event_data)
                    total_events += 1

            self.stdout.write(f"  Generated {count_per_type * len(user_agents)} events for {category}")

        self.stdout.write(self.style.SUCCESS(f"\nGenerated {total_events} total events"))
        self.stdout.write("\nTo verify, run these queries in the SQL editor:")
        self.stdout.write("""
SELECT __preview_getTrafficType(properties.$raw_user_agent) as traffic_type, count()
FROM events
WHERE properties.$lib = 'bot-demo-generator'
GROUP BY traffic_type
ORDER BY count() DESC

SELECT __preview_getTrafficCategory(properties.$raw_user_agent) as category, count()
FROM events
WHERE properties.$lib = 'bot-demo-generator'
GROUP BY category
ORDER BY count() DESC
""")
