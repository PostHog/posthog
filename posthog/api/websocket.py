from channels.generic.websocket import AsyncWebsocketConsumer
from rest_framework.exceptions import Throttled
from rest_framework.views import APIView
from rest_framework.request import Request
from django.contrib.auth.models import AnonymousUser
from asgiref.sync import sync_to_async

from django.test import RequestFactory
from typing import cast
import json


class BaseWebsocketConsumer(AsyncWebsocketConsumer):
    async def check_authentication(self):
        """Check if the user is authenticated."""
        user = self.scope.get("user", AnonymousUser())

        if not user.is_authenticated:
            await self.close(code=401)
            return False
        return True

    async def check_throttling(self, data):
        # Apply throttling
        throttles = self.get_throttles(data)
        view = APIView()  # DRF expects a view instance
        view.request = cast(Request, RequestFactory())
        view.request.user = self.scope["user"]  # Attach the user object

        try:
            for throttle in throttles:
                if not await sync_to_async(throttle.allow_request)(view.request, view):
                    raise Throttled()
        except Throttled as e:
            await self.send(
                json.dumps(
                    {
                        "status": 429,
                        "error": f"Rate limit exceeded: {str(e.detail)}",
                    }
                )
            )
            return False

        return True
