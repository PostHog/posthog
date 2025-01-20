from unittest.mock import patch
from freezegun import freeze_time
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase
from posthog.rate_limit import ClickHouseSustainedRateThrottle
from asgiref.sync import sync_to_async
from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.project import Project
import random


from posthog.asgi import application

from typing import Optional

import functools


class AuthWebsocketCommunicator(WebsocketCommunicator):
    def __init__(self, application, path, user, *args, **kwargs):
        super().__init__(self._asgi_with_user(application, user), path, *args, **kwargs)

    @classmethod
    def _asgi_with_user(cls, asgi_app, user):
        """
        Update the scope of an ASGI app such that a particular user
        is already assumed to have been authenticated.
        """

        async def app(scope, receive, send):
            scope["user"] = user
            return await asgi_app(scope, receive, send)

        functools.update_wrapper(app, asgi_app)
        return app


class TestQueryConsumer(TransactionTestCase):
    user: Optional[User] = None

    async def _create_user(self):
        # self.team = self.create_team_with_organization(self.organization)
        # self.user = self.create_user_with_organization(self.organization)

        if self.user:
            return self.user
        org = await Organization.objects.acreate(slug=f"org-{random.randint(1, 1000000)}")
        project_id = await sync_to_async(Team.objects.increment_id_sequence)()
        project = await Project.objects.acreate(id=project_id, organization=org)
        await Team.objects.acreate(organization=org, project=project)
        self.user = await User.objects.acreate(email=f"bla-{random.randint(1, 10000000)}@bla.com")

        await sync_to_async(org.members.add)(self.user)
        return self.user

    @freeze_time("2025-01-01 12:00:00")
    async def test_query_consumer_success(self):
        # Test a successful query
        communicator = AuthWebsocketCommunicator(application, "/ws/query/", await self._create_user())
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        query = {"query": {"select": ["count()", "event"], "where": ["event == 'sign up'"]}}
        await communicator.send_json_to(query)

        response = await communicator.receive_json_from()
        self.assertEqual(response["status"], 200, response)
        self.assertIn("result", response)
        self.assertIn("client_query_id", response)

        await communicator.disconnect()

    @freeze_time("2025-01-01 12:00:00")
    async def test_rate_limit_exceeded(self):
        # Test rate limit exceeded scenario
        with patch.object(ClickHouseSustainedRateThrottle, "allow_request", return_value=False):
            communicator = AuthWebsocketCommunicator(application, "/ws/query/", await self._create_user())
            # Authenticate the user
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            query = {"query": {"select": ["count()", "event"]}}
            await communicator.send_json_to(query)

            response = await communicator.receive_json_from()
            self.assertEqual(response["status"], 429, response)
            self.assertEqual(response["error"], "Rate limit exceeded: Request was throttled.")

            await communicator.disconnect()

    async def test_unauthenticated_access(self):
        # Test unauthenticated access
        communicator = WebsocketCommunicator(application, "/ws/query/")
        connected, code = await communicator.connect()
        self.assertFalse(connected)
        self.assertEqual(code, 401)
