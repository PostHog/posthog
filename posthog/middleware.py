from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed
from django.http import HttpResponse, HttpRequest
import re

class AllowIP(object):
    def __init__(self, get_response):
        if getattr(settings, 'ALLOWED_IP_BLOCKS', False):
            self.re_compiled = re.compile(settings.ALLOWED_IP_BLOCKS) # type: ignore
        else:
            # this will make Django skip this middleware for all future requests
            raise MiddlewareNotUsed()

        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        response: HttpResponse = self.get_response(request)
        if request.path.split('/')[1] in ['decide', 'engage', 'track', 'capture', 'batch', 'e']:
            return response
        ip = request.META['REMOTE_ADDR']
        if  self.re_compiled.match(ip):
            return response
        return HttpResponse("Your IP is not allowed. Check your ALLOWED_IP_BLOCKS settings")
