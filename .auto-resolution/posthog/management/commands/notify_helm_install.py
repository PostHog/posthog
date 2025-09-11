# ruff: noqa: T201 allow print statements
# ruff: noqa: T203 allow pprint statements

import os
from pprint import pprint

from django.conf import settings
from django.core.management.base import BaseCommand

import posthoganalytics

from posthog.utils import get_helm_info_env, get_machine_id


class Command(BaseCommand):
    help = "Notify that helm install/upgrade has happened"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", type=bool, help="Print information instead of sending it")

    def handle(self, *args, **options):
        report = get_helm_info_env()
        report["deployment"] = os.getenv("DEPLOYMENT", "unknown")

        print(f"Report for {get_machine_id()}:")
        pprint(report)

        if not options["dry_run"]:
            posthoganalytics.api_key = "sTMFPsFhdP1Ssg"
            disabled = posthoganalytics.disabled
            posthoganalytics.disabled = False
            posthoganalytics.capture(
                distinct_id=get_machine_id(),
                event="helm_install",
                properties=report,
                groups={"instance": settings.SITE_URL},
            )
            posthoganalytics.disabled = disabled
