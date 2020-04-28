from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed
from django.http import HttpResponse, HttpRequest
from posthog.utils import get_ip_address
from ipaddress import ip_address, ip_network
import re

class AllowIP(object):
    def __init__(self, get_response):
        if getattr(settings, 'ALLOWED_IP_BLOCKS', False):
            self.ip_blocks = [item.strip() for item in settings.ALLOWED_IP_BLOCKS.split(',')]  # type: ignore
        else:
            # this will make Django skip this middleware for all future requests
            raise MiddlewareNotUsed()

        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        response: HttpResponse = self.get_response(request)
        if request.path.split('/')[1] in ['decide', 'engage', 'track', 'capture', 'batch', 'e']:
            return response
        ip = get_ip_address(request)
        if any(ip_address(ip) in ip_network(block, strict=False) for block in self.ip_blocks):
            return response
        return HttpResponse("Your IP is not allowed. Check your ALLOWED_IP_BLOCKS settings")
