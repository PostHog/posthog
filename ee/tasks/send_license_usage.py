import posthoganalytics
import requests
from dateutil.relativedelta import relativedelta
from django.utils import timezone

from ee.models.license import License
from posthog.client import sync_execute
from posthog.models import User
from posthog.settings import SITE_URL
from posthog.tasks.status_report import get_instance_licenses


def send_license_usage():
    license = License.objects.first_valid()
    user = User.objects.filter(is_active=True).first()
    if not license:
        return
    try:
        date_from = (timezone.now() - relativedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        date_to = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        events_count = sync_execute(
            "select count(1) from events where timestamp >= %(date_from)s and timestamp < %(date_to)s and not startsWith(event, '$$')",
            {"date_from": date_from, "date_to": date_to},
        )[0][0]
        response = requests.post(
            "https://license.posthog.com/licenses/usage",
            data={"date": date_from.strftime("%Y-%m-%d"), "key": license.key, "events_count": events_count,},
        )

        response.raise_for_status()
        if not response.ok:
            posthoganalytics.capture(
                user.distinct_id,  # type: ignore
                "send license usage data error",
                {
                    "error": response.content,
                    "status_code": response.status_code,
                    "date": date_from.strftime("%Y-%m-%d"),
                    "events_count": events_count,
                    "organization_name": user.current_organization.name,  # type: ignore
                },
                groups={"organization": str(user.current_organization.id), "instance": SITE_URL,},  # type: ignore
            )
            return

        posthoganalytics.capture(
            user.distinct_id,  # type: ignore
            "send license usage data",
            {
                "date": date_from.strftime("%Y-%m-%d"),
                "events_count": events_count,
                "license_keys": get_instance_licenses(),
                "organization_name": user.current_organization.name,  # type: ignore
            },
            groups={"organization": str(user.current_organization.id), "instance": SITE_URL,},  # type: ignore
        )
    except Exception as err:
        posthoganalytics.capture(
            user.distinct_id,  # type: ignore
            "send license usage data error",
            {
                "error": str(err),
                "date": date_from.strftime("%Y-%m-%d"),
                "organization_name": user.current_organization.name,  # type: ignore
            },
            groups={"organization": str(user.current_organization.id), "instance": SITE_URL,},  # type: ignore
        )
