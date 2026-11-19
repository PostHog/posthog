"""
Write the llm-gateway organization entry for every team, or for the teams given.

The gateway's org-wallet admission reads the entry for every billed team, so a team without one can't
spend. Billing status changes and team creation keep entries current, and this covers the teams that
existed before them.

Usage:
    python manage.py warm_llm_gateway_org_cache
    python manage.py warm_llm_gateway_org_cache --team-ids 12345 67890
    python manage.py warm_llm_gateway_org_cache --batch-size 500 --min-ttl-days 5 --max-ttl-days 7
"""

from django.conf import settings

from posthog.management.commands._base_hypercache_command import BaseHyperCacheCommand
from posthog.storage.team_llm_gateway_org_cache import LLM_GATEWAY_ORG_HYPERCACHE_MANAGEMENT_CONFIG


class Command(BaseHyperCacheCommand):
    help = "Write the llm-gateway organization entry for every team"

    def add_arguments(self, parser):
        self.add_common_team_arguments(parser)
        self.add_warm_arguments(parser)

    def handle(self, *args, **options):
        # The entries live in the AI gateway's Redis, not the flags Redis the base class checks.
        if not settings.AI_GATEWAY_REDIS_URL:
            self.stdout.write(self.style.ERROR("AI_GATEWAY_REDIS_URL is not set, so there is no gateway cache to warm"))
            return
        batch_size = options["batch_size"]
        min_ttl_days, max_ttl_days = options["min_ttl_days"], options["max_ttl_days"]
        if not self.validate_batch_size(batch_size) or not self.validate_ttl_range(min_ttl_days, max_ttl_days):
            return
        self.run_warm(
            team_ids=options.get("team_ids"),
            batch_size=batch_size,
            stagger_ttl=not options["no_stagger"],
            min_ttl_days=min_ttl_days,
            max_ttl_days=max_ttl_days,
        )

    def get_hypercache_config(self):
        return LLM_GATEWAY_ORG_HYPERCACHE_MANAGEMENT_CONFIG
