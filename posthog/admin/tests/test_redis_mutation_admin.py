import json

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.admin.utils import flatten_fieldsets
from django.test import RequestFactory
from django.test.client import Client
from rest_framework import status

from posthog.admin.admins.redis_mutation_admin import RedisMutationAdmin
from posthog.api.test.test_organization import create_organization
from posthog.models import User
from posthog.models.redis import RedisMutation
from posthog.redis import get_client


@pytest.fixture
def request_factory():
    return RequestFactory()


@pytest.fixture
def admin():
    admin = RedisMutationAdmin(model=RedisMutation, admin_site=AdminSite())
    return admin


@pytest.fixture
def superuser():
    organization = create_organization("Test Org")
    superuser = User.objects.create_and_join(organization, "test@posthog.com", "abcde12345", is_staff=True)
    return superuser


@pytest.fixture
def redis():
    return get_client()


def test_validate_command_valid_append(request_factory, admin):
    """Test validation of a valid APPEND mutation."""
    data = {"value": "anything", "command": "append", "redis_key": "a-key", "approval_threshold": 1}

    request = request_factory.post("/admin/redismutation/add/", data=data)
    fieldsets = admin.get_fieldsets(request, obj=None)
    ModelForm = admin.get_form(request, obj=None, change=False, fields=flatten_fieldsets(fieldsets))
    form = ModelForm(request.POST, request.FILES, instance=None)

    assert form.is_valid() is True


def test_validate_command_fails_append_without_value(request_factory, admin):
    """Test validation of an invalid APPEND mutation missing a value."""
    data = {"command": "append", "redis_key": "a-key", "approval_threshold": 1}

    request = request_factory.post("/admin/redismutation/add/", data=data)
    fieldsets = admin.get_fieldsets(request, obj=None)
    ModelForm = admin.get_form(request, obj=None, change=False, fields=flatten_fieldsets(fieldsets))
    form = ModelForm(request.POST, request.FILES, instance=None)

    assert form.is_valid() is False
    assert (
        "Failed to validate command 'APPEND' on key 'a-key' of type 'None' with value 'None'." in form.errors["__all__"]
    )
    assert len(form.errors["__all__"]) == 1


def test_validate_command_valid_del(request_factory, admin):
    """Test validation of a valid DEL mutation."""
    data = {"command": "del", "redis_key": "a-key", "approval_threshold": 1}

    request = request_factory.post("/admin/redismutation/add/", data=data)
    fieldsets = admin.get_fieldsets(request, obj=None)
    ModelForm = admin.get_form(request, obj=None, change=False, fields=flatten_fieldsets(fieldsets))
    form = ModelForm(request.POST, request.FILES, instance=None)

    assert form.is_valid() is True, form.errors


def test_validate_command_valid_set(request_factory, admin):
    """Test validation of a valid SET mutation."""
    data = {"value": "anything", "command": "set", "redis_key": "a-key", "approval_threshold": 1}

    request = request_factory.post("/admin/redismutation/add/", data=data)
    fieldsets = admin.get_fieldsets(request, obj=None)
    ModelForm = admin.get_form(request, obj=None, change=False, fields=flatten_fieldsets(fieldsets))
    form = ModelForm(request.POST, request.FILES, instance=None)

    assert form.is_valid() is True


def test_validate_command_fails_set_without_value(request_factory, admin):
    """Test validation of an invalid SET mutation missing a value."""
    data = {"command": "set", "redis_key": "a-key", "approval_threshold": 1}

    request = request_factory.post("/admin/redismutation/add/", data=data)
    fieldsets = admin.get_fieldsets(request, obj=None)
    ModelForm = admin.get_form(request, obj=None, change=False, fields=flatten_fieldsets(fieldsets))
    form = ModelForm(request.POST, request.FILES, instance=None)

    assert form.is_valid() is False
    assert "Failed to validate command 'SET' on key 'a-key' of type 'None' with value 'None'." in form.errors["__all__"]
    assert len(form.errors["__all__"]) == 1


def test_validate_command_valid_expire(request_factory, admin):
    """Test validation of a valid EXPIRE mutation."""
    data = {"value": 1, "command": "expire", "redis_key": "a-key", "approval_threshold": 2}

    request = request_factory.post("/admin/redismutation/add/", data=data)
    fieldsets = admin.get_fieldsets(request, obj=None)
    ModelForm = admin.get_form(request, obj=None, change=False, fields=flatten_fieldsets(fieldsets))
    form = ModelForm(request.POST, request.FILES, instance=None)

    assert form.is_valid() is True


def test_validate_command_fails_expire_without_int_value(request_factory, admin):
    """Test validate of an invalid EXPIRE mutation with a non-int value."""
    data = {"value": "something that is not an int", "command": "expire", "redis_key": "a-key", "approval_threshold": 2}

    request = request_factory.post("/admin/redismutation/add/", data=data)
    fieldsets = admin.get_fieldsets(request, obj=None)
    ModelForm = admin.get_form(request, obj=None, change=False, fields=flatten_fieldsets(fieldsets))
    form = ModelForm(request.POST, request.FILES, instance=None)

    assert form.is_valid() is False
    assert (
        "EXPIRE requires the provided value of 'something that is not an int' to be castable to 'int'."
        in form.errors["__all__"]
    )
    assert len(form.errors["__all__"]) == 1


def test_validate_command_valid_lpush(request_factory, admin):
    """Test validation of a valid LPUSH mutation."""
    data = {"value": "a-value", "command": "lpush", "redis_key": "a-key", "approval_threshold": 2}

    request = request_factory.post("/admin/redismutation/add/", data=data)
    fieldsets = admin.get_fieldsets(request, obj=None)
    ModelForm = admin.get_form(request, obj=None, change=False, fields=flatten_fieldsets(fieldsets))
    form = ModelForm(request.POST, request.FILES, instance=None)

    assert form.is_valid() is True, form.errors


def test_validate_command_fails_with_wrong_type_for_lpush(request_factory, admin, redis):
    """Test validate of an invalid LPUSH mutation targetting a non-LIST key."""
    key = "a-string-key-that-is-not-a-list"
    value = "a-default-value"
    redis.set(key, value)

    data = {"value": "a-value", "command": "lpush", "redis_key": key, "approval_threshold": 2}

    request = request_factory.post("/admin/redismutation/add/", data=data)
    fieldsets = admin.get_fieldsets(request, obj=None)
    ModelForm = admin.get_form(request, obj=None, change=False, fields=flatten_fieldsets(fieldsets))
    form = ModelForm(request.POST, request.FILES, instance=None)

    assert form.is_valid() is False
    assert (
        "Failed to validate command 'LPUSH' on key 'a-string-key-that-is-not-a-list' of type 'string' with value 'a-value'."
        in form.errors["__all__"]
    )
    assert len(form.errors["__all__"]) == 1


def test_validate_command_valid_lset(request_factory, admin):
    """Test validation of a valid LSET mutation."""
    data = {
        "value": json.dumps({"value": "new-value", "index": 10}),
        "command": "lset",
        "redis_key": "a-key",
        "approval_threshold": 2,
    }

    request = request_factory.post("/admin/redismutation/add/", data=data)
    fieldsets = admin.get_fieldsets(request, obj=None)
    ModelForm = admin.get_form(request, obj=None, change=False, fields=flatten_fieldsets(fieldsets))
    form = ModelForm(request.POST, request.FILES, instance=None)

    assert form.is_valid() is True, form.errors


def test_validate_command_fails_with_wrong_type_for_lset(request_factory, admin, redis):
    """Test validate of an invalid LSET mutation targetting a non-LIST key."""
    key = "a-string-key-that-is-not-a-list"
    value = "a-default-value"
    redis.set(key, value)

    data = {
        "value": json.dumps({"value": "new-value", "index": 10}),
        "command": "lset",
        "redis_key": key,
        "approval_threshold": 2,
    }

    request = request_factory.post("/admin/redismutation/add/", data=data)
    fieldsets = admin.get_fieldsets(request, obj=None)
    ModelForm = admin.get_form(request, obj=None, change=False, fields=flatten_fieldsets(fieldsets))
    form = ModelForm(request.POST, request.FILES, instance=None)

    assert form.is_valid() is False
    assert (
        "Failed to validate command 'LSET' on key 'a-string-key-that-is-not-a-list' of type 'string' with value '{'value': 'new-value', 'index': 10}'."
        in form.errors["__all__"]
    )
    assert len(form.errors["__all__"]) == 1


def test_validate_command_fails_with_no_index_for_lset(request_factory, admin, redis):
    """Test validate of an invalid LSET mutation without an index."""
    key = "a-string-key-that-is-not-a-list"
    value = "a-default-value"
    redis.set(key, value)

    data = {
        "value": json.dumps({"value": "new-value"}),
        "command": "lset",
        "redis_key": key,
        "approval_threshold": 2,
    }

    request = request_factory.post("/admin/redismutation/add/", data=data)
    fieldsets = admin.get_fieldsets(request, obj=None)
    ModelForm = admin.get_form(request, obj=None, change=False, fields=flatten_fieldsets(fieldsets))
    form = ModelForm(request.POST, request.FILES, instance=None)

    assert form.is_valid() is False
    assert (
        "Failed to validate command 'LSET' on key 'a-string-key-that-is-not-a-list' of type 'string' with value '{'value': 'new-value'}'."
        in form.errors["__all__"]
    )
    assert len(form.errors["__all__"]) == 1


def test_validate_command_valid_sadd(request_factory, admin):
    """Test validation of a valid SADD mutation."""
    data = {"value": "a-value", "command": "sadd", "redis_key": "a-key", "approval_threshold": 2}

    request = request_factory.post("/admin/redismutation/add/", data=data)
    fieldsets = admin.get_fieldsets(request, obj=None)
    ModelForm = admin.get_form(request, obj=None, change=False, fields=flatten_fieldsets(fieldsets))
    form = ModelForm(request.POST, request.FILES, instance=None)

    assert form.is_valid() is True, form.errors


def test_validate_command_fails_with_wrong_type_for_sadd(request_factory, admin, redis):
    """Test validate of an invalid SADD mutation targetting a non-SET key."""
    key = "a-string-key-that-is-not-a-set"
    value = "a-default-value"
    redis.set(key, value)

    data = {"value": "a-value", "command": "sadd", "redis_key": key, "approval_threshold": 2}

    request = request_factory.post("/admin/redismutation/add/", data=data)
    fieldsets = admin.get_fieldsets(request, obj=None)
    ModelForm = admin.get_form(request, obj=None, change=False, fields=flatten_fieldsets(fieldsets))
    form = ModelForm(request.POST, request.FILES, instance=None)

    assert form.is_valid() is False
    assert (
        "Failed to validate command 'SADD' on key 'a-string-key-that-is-not-a-set' of type 'string' with value 'a-value'."
        in form.errors["__all__"]
    )
    assert len(form.errors["__all__"]) == 1


def test_validate_command_fails_on_unknown_command(request_factory, admin):
    """Test validation of an invalid unknown command."""
    data = {"value": 1, "command": "unknown", "redis_key": "a-key", "approval_threshold": 2}

    request = request_factory.post("/admin/redismutation/add/", data=data)
    fieldsets = admin.get_fieldsets(request, obj=None)
    ModelForm = admin.get_form(request, obj=None, change=False, fields=flatten_fieldsets(fieldsets))
    form = ModelForm(request.POST, request.FILES, instance=None)

    assert form.is_valid() is False
    assert "Command is not a valid choice" in form.errors["__all__"]


@pytest.mark.django_db
def test_creation_of_append_redis_mutation(client: Client, superuser, redis):
    """Test the creation of a APPEND Redis mutation."""
    client.force_login(superuser)

    key = "an-append-test-key"
    value = "a-append-test-value"
    redis.set(key, value)

    data = {"value": "anything", "command": "append", "redis_key": key, "approval_threshold": 1}

    response = client.post(
        f"/admin/posthog/redismutation/add/",
        data,
    )

    # 200 means the form is being re-displayed with errors
    assert response.status_code == status.HTTP_302_FOUND

    mutation = RedisMutation.objects.filter(redis_key=key).first()
    assert mutation is not None
    assert mutation.command == RedisMutation.MutationCommand.APPEND
    assert mutation.value == "anything"
    assert mutation.approval_threshold == 1
    assert mutation.redis_key == key
    assert mutation.redis_type == RedisMutation.RedisType.STRING
    assert mutation.status == RedisMutation.Status.CREATED


@pytest.mark.django_db
def test_creation_of_del_redis_mutation(client: Client, superuser, redis):
    """Test the creation of a DEL Redis mutation."""
    client.force_login(superuser)

    key = "a-del-test-key"
    value = "a-default-value"
    redis.set(key, value)

    data = {"command": "del", "redis_key": key, "approval_threshold": 1}

    response = client.post(
        f"/admin/posthog/redismutation/add/",
        data,
    )

    # 200 means the form is being re-displayed with errors
    assert response.status_code == status.HTTP_302_FOUND

    mutation = RedisMutation.objects.filter(redis_key=key).first()
    assert mutation is not None
    assert mutation.command == RedisMutation.MutationCommand.DEL
    assert mutation.value is None
    assert mutation.approval_threshold == 1
    assert mutation.redis_key == key
    assert mutation.redis_type == RedisMutation.RedisType.STRING
    assert mutation.status == RedisMutation.Status.CREATED


@pytest.mark.django_db
def test_creation_of_expire_redis_mutation(client: Client, superuser, redis):
    """Test the creation of an EXPIRE Redis mutation."""
    client.force_login(superuser)

    key = "an-expire-test-key"
    value = "a-default-value"
    redis.set(key, value)

    data = {"command": "expire", "value": 10, "redis_key": key, "approval_threshold": 1}

    response = client.post(
        f"/admin/posthog/redismutation/add/",
        data,
    )

    # 200 means the form is being re-displayed with errors
    assert response.status_code == status.HTTP_302_FOUND

    mutation = RedisMutation.objects.filter(redis_key=key).first()
    assert mutation is not None
    assert mutation.command == RedisMutation.MutationCommand.EXPIRE
    assert int(mutation.value) == 10  # type: ignore
    assert mutation.approval_threshold == 1
    assert mutation.redis_key == key
    assert mutation.redis_type == RedisMutation.RedisType.STRING
    assert mutation.status == RedisMutation.Status.CREATED


@pytest.mark.django_db
def test_creation_of_lpush_redis_mutation(client: Client, superuser, redis):
    """Test the creation of an LPUSH Redis mutation."""
    client.force_login(superuser)

    key = "an-lpush-test-key"
    value = "a-default-value"
    redis.lpush(key, value)

    data = {"command": "lpush", "value": "new-value", "redis_key": key, "approval_threshold": 1}

    response = client.post(
        f"/admin/posthog/redismutation/add/",
        data,
    )

    # 200 means the form is being re-displayed with errors
    assert response.status_code == status.HTTP_302_FOUND

    mutation = RedisMutation.objects.filter(redis_key=key).first()
    assert mutation is not None
    assert mutation.command == RedisMutation.MutationCommand.LPUSH
    assert mutation.value == "new-value"
    assert mutation.approval_threshold == 1
    assert mutation.redis_key == key
    assert mutation.redis_type == RedisMutation.RedisType.LIST
    assert mutation.status == RedisMutation.Status.CREATED


@pytest.mark.django_db
def test_creation_of_lset_redis_mutation(client: Client, superuser, redis):
    """Test the creation of an LSET Redis mutation."""
    client.force_login(superuser)

    key = "an-lpush-test-key"
    value = "a-default-value"
    redis.lpush(key, value)

    data = {
        "command": "lset",
        "value": json.dumps({"value": "new-value", "index": 10}),
        "redis_key": key,
        "approval_threshold": 1,
    }

    response = client.post(
        f"/admin/posthog/redismutation/add/",
        data,
    )

    # 200 means the form is being re-displayed with errors
    assert response.status_code == status.HTTP_302_FOUND

    mutation = RedisMutation.objects.filter(redis_key=key).first()
    assert mutation is not None
    assert mutation.command == RedisMutation.MutationCommand.LSET
    assert mutation.value == {"value": "new-value", "index": 10}
    assert mutation.approval_threshold == 1
    assert mutation.redis_key == key
    assert mutation.redis_type == RedisMutation.RedisType.LIST
    assert mutation.status == RedisMutation.Status.CREATED


@pytest.mark.django_db
def test_creation_of_set_redis_mutation(client: Client, superuser, redis):
    """Test the creation of a SET Redis mutation."""
    client.force_login(superuser)

    key = "a-set-test-key"
    value = "a-set-test-value"
    redis.set(key, value)

    data = {
        "value": "anything",
        "command": "set",
        "redis_key": key,
        "approval_threshold": 1,
        # BEWARE: Failing to pass a valid JSON can raise an unrelated exception.
        # Try re-running this test without parameters if you see some strange failure.
        "parameters": '{"get": true}',
    }

    response = client.post(
        f"/admin/posthog/redismutation/add/",
        data,
    )

    # 200 means the form is being re-displayed with errors
    assert response.status_code == status.HTTP_302_FOUND

    mutation = RedisMutation.objects.filter(redis_key=key).first()
    assert mutation is not None
    assert mutation.command == RedisMutation.MutationCommand.SET
    assert mutation.value == "anything"
    assert mutation.approval_threshold == 1
    assert mutation.redis_key == key
    assert mutation.redis_type == RedisMutation.RedisType.STRING
    assert mutation.status == RedisMutation.Status.CREATED


@pytest.mark.django_db
def test_creation_of_sadd_redis_mutation(client: Client, superuser, redis):
    """Test the creation of a SADD Redis mutation."""
    client.force_login(superuser)

    key = "an-sadd-test-key"
    value = "a-sadd-test-value"
    redis.sadd(key, value)

    data = {"value": "another-sadd-test-value", "command": "sadd", "redis_key": key, "approval_threshold": 1}

    response = client.post(
        f"/admin/posthog/redismutation/add/",
        data,
    )

    # 200 means the form is being re-displayed with errors
    assert response.status_code == status.HTTP_302_FOUND

    mutation = RedisMutation.objects.filter(redis_key=key).first()
    assert mutation is not None
    assert mutation.command == RedisMutation.MutationCommand.SADD
    assert mutation.value == "another-sadd-test-value"
    assert mutation.approval_threshold == 1
    assert mutation.redis_key == key
    assert mutation.redis_type == RedisMutation.RedisType.SET
    assert mutation.status == RedisMutation.Status.CREATED


@pytest.mark.django_db
def test_creation_of_zadd_redis_mutation(client: Client, superuser, redis):
    """Test the creation of a ZADD Redis mutation."""
    client.force_login(superuser)

    key = "an-zadd-test-key"
    value = "a-default-value"
    score = 10
    redis.zadd(key, {value: score})

    data = {
        "command": "zadd",
        "value": json.dumps({"new-value": 99}),
        "redis_key": key,
        "approval_threshold": 1,
    }

    response = client.post(
        f"/admin/posthog/redismutation/add/",
        data,
    )

    # 200 means the form is being re-displayed with errors
    assert response.status_code == status.HTTP_302_FOUND

    mutation = RedisMutation.objects.filter(redis_key=key).first()
    assert mutation is not None
    assert mutation.command == RedisMutation.MutationCommand.ZADD
    assert mutation.value == {"new-value": 99}
    assert mutation.approval_threshold == 1
    assert mutation.redis_key == key
    assert mutation.redis_type == RedisMutation.RedisType.ZSET
    assert mutation.status == RedisMutation.Status.CREATED


@pytest.mark.django_db
def test_creation_of_zincrby_redis_mutation(client: Client, superuser, redis):
    """Test the creation of a ZINCRBY Redis mutation."""
    client.force_login(superuser)

    key = "an-zadd-test-key"
    value = "a-default-value"
    score = 10
    redis.zadd(key, {value: score})

    data = {
        "command": "zincrby",
        "value": json.dumps({"amount": 99, "value": "a-default-value"}),
        "redis_key": key,
        "approval_threshold": 1,
    }

    response = client.post(
        f"/admin/posthog/redismutation/add/",
        data,
    )

    # 200 means the form is being re-displayed with errors
    assert response.status_code == status.HTTP_302_FOUND

    mutation = RedisMutation.objects.filter(redis_key=key).first()
    assert mutation is not None
    assert mutation.command == RedisMutation.MutationCommand.ZINCRBY
    assert mutation.value == {"amount": 99, "value": "a-default-value"}
    assert mutation.approval_threshold == 1
    assert mutation.redis_key == key
    assert mutation.redis_type == RedisMutation.RedisType.ZSET
    assert mutation.status == RedisMutation.Status.CREATED
