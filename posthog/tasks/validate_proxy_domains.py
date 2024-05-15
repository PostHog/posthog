import dns.resolver
import requests
import json
from posthog.models import ProxyRecord
from django.conf import settings

EXPECTED_CNAME = settings.PROXY_TARGET_CNAME


def validate_proxy_domains():
    records = ProxyRecord.objects.filter(status=ProxyRecord.Status.WAITING)
    for record in records:
        try:
            domain = record.domain
            cnames = dns.resolver.query(domain, "CNAME")
            value = cnames[0].target.canonicalize().to_text()

            if value == EXPECTED_CNAME:
                record.status = ProxyRecord.Status.ISSUING
                response = requests.post(f"{settings.PROXY_PROVISIONER_URL}create", data=json.dumps({"domain": record.domain}))
                if response.status_code != 200:
                    record.status = ProxyRecord.Status.ERRORING
                record.save()
        except dns.resolver.NoAnswer:
            break

    records = ProxyRecord.objects.filter(status=ProxyRecord.Status.ISSUING)
    for record in records:
        response = requests.post(f"{settings.PROXY_PROVISIONER_URL}status", data=json.dumps({"domain": record.domain}))
        if response.status_code != 200:
            record.status = ProxyRecord.Status.ERRORING
            record.save()
        else:
            data = response.json()
            if data.get("status") == "Ready":
                record.status = ProxyRecord.Status.VALID
                record.save()

    records = ProxyRecord.objects.filter(status=ProxyRecord.Status.DELETING)
    for record in records:
        response = requests.post(f"{settings.PROXY_PROVISIONER_URL}delete", data=json.dumps({"domain": record.domain}))
        if response.status_code != 200:
            record.status = ProxyRecord.Status.ERRORING
            record.save()
        else:
            record.delete()
