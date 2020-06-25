import re
from ipaddress import ip_address, ip_network

from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed
from django.http import HttpResponse, HttpRequest
from ipaddress import ip_address, ip_network
import re

class AllowIP(object):
    def __init__(self, get_response):
        if not settings.ALLOWED_IP_BLOCKS:
            # this will make Django skip this middleware for all future requests
            raise MiddlewareNotUsed()
        self.ip_blocks = settings.ALLOWED_IP_BLOCKS

        if getattr(settings, 'TRUSTED_PROXIES', False):
            self.trusted_proxies = [item.strip() for item in getattr(settings, 'TRUSTED_PROXIES').split(',')]
        self.get_response = get_response

    def get_forwarded_for(self, request: HttpRequest):
        forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if forwarded_for is not None:
            return [ip.strip() for ip in forwarded_for.split(',')]
        else:
            return []

    def extract_client_ip(self, request: HttpRequest):
        client_ip = request.META['REMOTE_ADDR']
        if getattr(settings, 'USE_X_FORWARDED_HOST', False):
            forwarded_for = self.get_forwarded_for(request)
            if forwarded_for:
                closest_proxy = client_ip
                client_ip = forwarded_for.pop(0)
                if getattr(settings, 'TRUST_ALL_PROXIES', False):
                    return client_ip
                proxies = [closest_proxy] + forwarded_for
                for proxy in proxies:
                    if proxy not in self.trusted_proxies:
                        return None
        return client_ip

    def __call__(self, request: HttpRequest):
        response: HttpResponse = self.get_response(request)
        if request.path.split('/')[1] in ['decide', 'engage', 'track', 'capture', 'batch', 'e', 'static']:
            return response
        ip = self.extract_client_ip(request)
        if ip and any(ip_address(ip) in ip_network(block, strict=False) for block in self.ip_blocks):
            return response
        return HttpResponse("Your IP is not allowed. Check your ALLOWED_IP_BLOCKS settings. If you are behind a proxy, you need to set TRUSTED_PROXIES. See https://posthog.com/docs/deployment/running-behind-proxy")
