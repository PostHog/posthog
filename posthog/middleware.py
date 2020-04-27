import re
from ipaddress import ip_address, ip_network

from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed
from django.http import HttpRequest, HttpResponse


class AllowIP(object):
    def __init__(self, get_response):
        if not settings.ALLOWED_IP_BLOCKS:
            # this will make Django skip this middleware for all future requests
            raise MiddlewareNotUsed()

        self.ip_blocks = settings.ALLOWED_IP_BLOCKS
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        response: HttpResponse = self.get_response(request)
        if request.path.split('/')[1] in ['decide', 'engage', 'track', 'capture', 'batch', 'e']:
            return response
        ip = request.META['REMOTE_ADDR']
        if any(ip_address(ip) in ip_network(block, strict=False) for block in self.ip_blocks):
            return response
        return HttpResponse("Your IP is not allowed. Check your ALLOWED_IP_BLOCKS settings")
