from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.dns_hosts import detect_dns_host


class TestDetectDnsHost(SimpleTestCase):
    @parameterized.expand(
        [
            (["ns-1234.awsdns-56.org.", "ns-789.awsdns-12.co.uk."], "Route 53"),
            (["ns51.domaincontrol.com"], "GoDaddy"),
            (["dns1.registrar-servers.com"], "Namecheap"),
            (["ns-cloud-a1.squarespacedns.com"], "Squarespace"),
            (["ns1.dns-parking.com"], "Hostinger"),
            (["ns1.hostinger.com"], "Hostinger"),
            (["ns1045.ui-dns.de"], "IONOS"),
            (["ns1.digitalocean.com"], "DigitalOcean"),
            (["ADA.NS.CLOUDFLARE.COM."], "Cloudflare"),
            (["ns1.vercel-dns.com"], "Vercel"),
            (["ns1.mydigitalocean.com.evil.example"], None),
            (["ns1.example.com"], None),
            ([], None),
        ]
    )
    def test_names_host_from_nameservers(self, nameservers: list[str], expected: str | None) -> None:
        host = detect_dns_host(nameservers)
        assert (host.name if host else None) == expected
