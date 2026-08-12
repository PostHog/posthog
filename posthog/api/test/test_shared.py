from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.api.shared import UserBasicSerializer
from posthog.models import User


class TestUserBasicSerializerHedgehogConfig(SimpleTestCase):
    @parameterized.expand(
        [
            ("null_actor_options", {"version": 2, "actor_options": None}),
            ("string_actor_options", {"version": 2, "actor_options": "nope"}),
            ("list_actor_options", {"version": 2, "actor_options": []}),
            ("config_is_a_string", "nope"),
            ("config_is_a_list", ["nope"]),
            ("config_is_a_number", 5),
        ]
    )
    def test_malformed_stored_config_is_coerced_rather_than_raising(self, _name, stored_config):
        user = User(email="poisoned@posthog.com", hedgehog_config=stored_config)

        data = UserBasicSerializer(user).data

        self.assertIsInstance(data["hedgehog_config"], dict | type(None))
