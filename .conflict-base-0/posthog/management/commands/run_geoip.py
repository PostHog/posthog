import logging
from pprint import pprint

from django.contrib.gis.geoip2 import GeoIP2
from django.core.management.base import BaseCommand

logging.getLogger("kafka").setLevel(logging.ERROR)  # Hide kafka-python's logspam


class Command(BaseCommand):
    help = "Run geoip2 for an ip address, try `DEBUG=1 ./manage.py run_geoip 138.84.47.0`"

    def add_arguments(self, parser):
        parser.add_argument("ip", type=str, help="IP Address")

    def handle(self, *args, **options):
        geoip = GeoIP2(cache=GeoIP2.MODE_MMAP)
        ip_arg = options.get("ip")
        if not isinstance(ip_arg, str):
            raise ValueError("ip not a string")

        ips = ip_arg.split(",")

        for ip in ips:
            ip = ip.strip()
            print("----------------------------------------")  # noqa: T201
            print(ip)  # noqa: T201
            pprint(geoip.city(ip))  # noqa: T203
