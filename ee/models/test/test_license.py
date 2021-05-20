import datetime
from unittest.mock import Mock

import pytest
from django.utils import timezone
from pytest_mock.plugin import MockerFixture

from ee.models.license import License, get_licensed_users_available
from posthog.models import User


@pytest.fixture
def create_license(mocker: MockerFixture):
    def _inner(key, max_users):
        mock = Mock()
        mock.ok = True
        mock.json.return_value = {
            "plan": key,
            "valid_until": (timezone.now() + datetime.timedelta(days=10)).isoformat().replace("+00:00", "Z"),
            "max_users": max_users,
        }

        mocker.patch("ee.models.license.requests.post", return_value=mock)
        License.objects.create(key=key)

    return _inner


def test_default_get_licensed_users_available(db):
    assert get_licensed_users_available() == 3


def test_uses_max_value_from_license(db, create_license):
    create_license("foo", max_users=2)
    create_license("bar", max_users=4)

    assert get_licensed_users_available() == 4

    create_license("unlimited", max_users=None)

    assert get_licensed_users_available() is None


def test_get_users_available_when_users_exist(db, create_license):
    create_license("bar", max_users=4)

    User.objects.create(email="test@posthog.com")
    User.objects.create(email="test2@posthog.com")

    assert get_licensed_users_available() == 2

    create_license("unlimited", max_users=None)

    assert get_licensed_users_available() is None
