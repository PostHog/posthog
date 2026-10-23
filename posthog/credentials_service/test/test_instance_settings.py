from collections.abc import Callable
from typing import Any

from unittest import mock

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.credentials_service import instance_settings
from posthog.credentials_service.callers import CredentialsCaller
from posthog.credentials_service.test.test_settings_fallback import (
    FLAG,
    POST,
    SERVICE_SETTINGS,
    _FakeResponse,
    _keys_asked_for,
    _missing,
    _steady,
)

KEY = "SLACK_APP_SIGNING_SECRET"
CALLER = CredentialsCaller.INTEGRATIONS
UNCONFIGURED: dict[str, Any] = {"CREDENTIALS_SERVICE_URL": "", "CREDENTIALS_SERVICE_JWT_SECRET": ""}

READS: dict[str, Callable[[], str]] = {
    "one": lambda: instance_settings.get_or_instance_setting(KEY, CALLER),
    "many": lambda: instance_settings.get_many_or_instance_settings([KEY], CALLER)[KEY],
}


class TestInstanceSettingsFallback(SimpleTestCase):
    @parameterized.expand(
        [
            (f"{read}_{name}", read, *case)
            for read in READS
            for name, *case in [
                # An operator's edit in the instance settings UI must win over the environment variable
                # it defaults from, so with the service off the environment is never read directly.
                ("unconfigured_reads_the_instance_setting", UNCONFIGURED, True, None, "edited", "edited"),
                ("flag_off_reads_the_instance_setting", SERVICE_SETTINGS, False, None, "edited", "edited"),
                ("service_value_wins", SERVICE_SETTINGS, True, "from-service", "edited", "from-service"),
                ("missing_falls_back_to_the_instance_setting", SERVICE_SETTINGS, True, None, "edited", "edited"),
                ("configured_nowhere", SERVICE_SETTINGS, True, None, "", ""),
            ]
        ]
    )
    def test_reads(
        self,
        _name: str,
        read: str,
        service_settings: dict[str, Any],
        flag_on: bool,
        service_value: str | None,
        instance_value: str,
        expected: str,
    ) -> None:
        response = (
            _FakeResponse({"secrets": {KEY: _steady(service_value)}, "missing": []})
            if service_value is not None
            else _missing(KEY)
        )
        with (
            override_settings(**service_settings),
            mock.patch(FLAG, return_value=flag_on),
            mock.patch(POST, return_value=response) as post,
            mock.patch.dict("os.environ", {KEY: "env-copy"}),
            mock.patch.object(instance_settings, "get_instance_setting", return_value=instance_value),
            mock.patch.object(instance_settings, "get_instance_settings", return_value={KEY: instance_value}),
        ):
            assert READS[read]() == expected

        if service_settings is SERVICE_SETTINGS and flag_on:
            assert _keys_asked_for(post.call_args.kwargs["headers"]["Authorization"]) == [KEY]
        else:
            post.assert_not_called()
