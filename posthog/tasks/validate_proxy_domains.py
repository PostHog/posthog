import dns.resolver
import requests
from posthog.models import ProxyRecord
from django.conf import settings

EXPECTED_CNAME = settings.PROXY_TARGET_CNAME


def validate_proxy_domains() -> None:
    records = ProxyRecord.objects.get(status=ProxyRecord.Status.WAITING)

    for record in records:
        try:
            domain = record.domain
            cnames = dns.resolver.query(domain, "CNAME")
            value = cnames[0].target.canonicalize().to_text()

            if value == EXPECTED_CNAME:
                domain.status = ProxyRecord.Status.ISSUING
                response = requests.post(f"{settings.PROXY_PROVISIONER_URL}create", data={"domain": record.domain})
                if response.status_code != 200:
                    domain.status = ProxyRecord.Status.ERRORING
                domain.save()
        except dns.resolver.NoAnswer:
            break

    records = ProxyRecord.objects.get(status=ProxyRecord.Status.ISSUING)

    for record in records:
        response = requests.post(f"{settings.PROXY_PROVISIONER_URL}status", data={"domain": record.domain})

        if response.status_code != 200:
            domain.status = ProxyRecord.Status.ERRORING

            domain.save()
        else:
            data = response.json()
            if data.get("status") == "Ready":
                domain.status = ProxyRecord.Status.VALID

            domain.save()
