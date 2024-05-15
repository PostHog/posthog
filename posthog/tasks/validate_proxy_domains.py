import dns
from posthog.models import ProxyRecord

RESOLVED_DOMAIN = "http://k8s-proxyasa-proxyasa-e8343c0048-1f26b5a36cde44fd.elb.us-east-1.amazonaws.com/"


def validate_proxy_domains() -> None:
    records = ProxyRecord.objects.get(status=ProxyRecord.Status.WAITING)

    for record in records:
        try:
            domain = record.domain
            cnames = dns.resolver.query(domain, "CNAME")
            value = cnames[0].target.canonicalize().to_text()

            if value == RESOLVED_DOMAIN:
                domain.status = ProxyRecord.Status.VALID
                domain.save()
        except dns.resolver.NoAnswer:
            break
