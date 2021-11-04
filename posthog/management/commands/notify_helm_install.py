import os
from pprint import pprint

import posthoganalytics
from django.core.management.base import BaseCommand

from posthog.settings import SITE_URL
from posthog.tasks.status_report import get_helm_info_env
from posthog.utils import get_machine_id
from posthog.version import VERSION


class Command(BaseCommand):
    help = "Notify that helm install/upgrade has happened"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", type=bool, help="Print information instead of sending it")

    def handle(self, *args, **options):
        report = get_helm_info_env()
        report["posthog_version"] = VERSION
        report["deployment"] = os.getenv("DEPLOYMENT", "unknown")

        print(f"Report for {get_machine_id()}:")
        pprint(report)

        if not options["dry_run"]:
            posthoganalytics.api_key = "sTMFPsFhdP1Ssg"
            disabled = posthoganalytics.disabled
            posthoganalytics.disabled = False
            posthoganalytics.capture(get_machine_id(), "helm_install", report, groups={"instance": SITE_URL})
            posthoganalytics.disabled = disabled
