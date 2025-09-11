from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

from rest_framework.request import Request


@csrf_exempt
def slack_interactivity_callback(request: Request) -> HttpResponse:
    # This is an empty endpoint for the Slack interactivity callback.
    # We don't verify the request, as we don't do anything with the submitted data.
    # We only use it to supress the warnings when users press buttons in Slack messages.
    # In case we decide to do something with it, please add the verification process here.
    return HttpResponse("")
