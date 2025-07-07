import posthoganalytics
import requests
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from django.utils.timezone import now

from ee.models.license import License
from posthog.clickhouse.client import sync_execute
from posthog.models import User
from posthog.settings import SITE_URL


def send_license_usage():
    license = License.objects.first_valid()
    user = User.objects.filter(is_active=True).first()

    if not license:
        return

    # New type of license key for billing
    if license.is_v2_license:
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
            data={
                "date": date_from.strftime("%Y-%m-%d"),
                "key": license.key,
                "events_count": events_count,
            },
        )

        if response.status_code == 404 and response.json().get("code") == "not_found":
            license.valid_until = now() - relativedelta(hours=1)
            license.save()

        if response.status_code == 400 and response.json().get("code") == "already_sent":
            return

        if response.json().get("valid_until"):
            license.valid_until = response.json()["valid_until"]
            license.save()

        if not response.ok:
            posthoganalytics.capture(
                "send license usage data error",
                distinct_id=user.distinct_id,  # type: ignore
                properties={
                    "error": response.content,
                    "status_code": response.status_code,
                    "date": date_from.strftime("%Y-%m-%d"),
                    "events_count": events_count,
                    "organization_name": user.current_organization.name,  # type: ignore
                },
                groups={
                    "organization": str(user.current_organization.id),  # type: ignore
                    "instance": SITE_URL,
                },
            )
            response.raise_for_status()
            return
        else:
            posthoganalytics.capture(
                "send license usage data",
                distinct_id=user.distinct_id,  # type: ignore
                properties={
                    "date": date_from.strftime("%Y-%m-%d"),
                    "events_count": events_count,
                    "license_keys": [license.key for license in License.objects.all()],
                    "organization_name": user.current_organization.name,  # type: ignore
                },
                groups={
                    "organization": str(user.current_organization.id),  # type: ignore
                    "instance": SITE_URL,
                },
            )
    except Exception as err:
        try:
            posthoganalytics.capture(
                "send license usage data error",
                distinct_id=user.distinct_id,  # type: ignore
                properties={
                    "error": str(err),
                    "date": date_from.strftime("%Y-%m-%d"),
                    "organization_name": user.current_organization.name,  # type: ignore
                },
                groups={
                    "organization": str(user.current_organization.id),  # type: ignore
                    "instance": SITE_URL,
                },
            )
            raise err
        except:
            # If the posthoganalytics call errors, just throw the original error rather than that error
            raise err
