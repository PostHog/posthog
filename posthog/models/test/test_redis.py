import pytest

from posthog.api.test.test_organization import create_organization
from posthog.models import RedisMutation, User
from posthog.models.redis import MutationInactiveError
from posthog.redis import get_client

pytestmark = [pytest.mark.django_db]


@pytest.fixture
def superuser():
    """A superuser for tests that require additional access."""
    organization = create_organization("Test Org")
    superuser = User.objects.create_and_join(organization, "test@posthog.com", "abcde12345", is_staff=True)
    return superuser


@pytest.fixture
def redis():
    """Redis test client."""
    return get_client()


@pytest.fixture()
def default_value():
    """Just a default value to be set."""
    return "a-default-value"


@pytest.fixture()
def redis_string_key(redis, default_value):
    """Return a default STRING type key that is cleaned up after use."""
    key = "a-default-string-key"
    redis.set(key, default_value)

    yield key

    redis.delete(key)


@pytest.fixture()
def redis_list_key(redis, default_value):
    """Return a default LIST type key that is cleaned up after use."""
    key = "a-default-list-key"
    redis.lpush(key, default_value)

    yield key

    redis.delete(key)


@pytest.fixture()
def redis_set_key(redis, default_value):
    """Return a default LIST type key that is cleaned up after use."""
    key = "a-default-set-key"
    redis.sadd(key, default_value)

    yield key

    redis.delete(key)


@pytest.fixture()
def redis_zset_key(redis, default_value):
    """Return a default LIST type key that is cleaned up after use."""
    key = "a-default-zset-key"
    redis.zadd(key, {default_value: 0})

    yield key

    redis.delete(key)


def test_mutation_can_be_approved(superuser):
    """Test a mutation is set to APPROVED status."""
    mutation = RedisMutation.objects.create(
        command=RedisMutation.MutationCommand.SET,
        redis_key="a-key",
        redis_type=RedisMutation.RedisType.STRING,
        approval_threshold=1,
        status=RedisMutation.Status.CREATED,
    )
    mutation.approve(approved_by=superuser.email)

    assert mutation.approvals == 1
    assert superuser.email in mutation.approved_by
    assert mutation.status == RedisMutation.Status.APPROVED


def test_mutation_not_approved_if_not_at_threshold(superuser):
    """Test a mutation is not set to APPROVED status if we haven't reached threshold."""
    mutation = RedisMutation.objects.create(
        command=RedisMutation.MutationCommand.SET,
        redis_key="a-key",
        redis_type=RedisMutation.RedisType.STRING,
        approval_threshold=2,
        status=RedisMutation.Status.CREATED,
    )
    mutation.approve(approved_by=superuser.email)

    assert mutation.approvals == 1
    assert superuser.email in mutation.approved_by
    assert mutation.status == RedisMutation.Status.CREATED


def test_mutation_can_be_discarded(superuser):
    """Test a mutation is set to DISCARDED status"""
    mutation = RedisMutation.objects.create(
        command=RedisMutation.MutationCommand.SET,
        redis_key="a-key",
        redis_type=RedisMutation.RedisType.STRING,
        approval_threshold=1,
        status=RedisMutation.Status.CREATED,
    )
    mutation.discard(discarded_by=superuser.email)

    assert mutation.status == RedisMutation.Status.DISCARDED
    assert mutation.discarded_by == superuser.email


def test_mutation_cannot_be_used_once_inactive(superuser):
    """Test a DISCARDED mutation cannot be used for any action anymore."""
    for inactive_status in (
        RedisMutation.Status.FAILED,
        RedisMutation.Status.COMPLETED,
        RedisMutation.Status.DISCARDED,
    ):
        mutation = RedisMutation.objects.create(
            command=RedisMutation.MutationCommand.SET,
            redis_key="a-key",
            redis_type=RedisMutation.RedisType.STRING,
            approval_threshold=1,
            status=inactive_status,
        )

        with pytest.raises(MutationInactiveError):
            mutation.approve(approved_by=superuser.email)

        with pytest.raises(MutationInactiveError):
            mutation.discard(discarded_by=superuser.email)

        with pytest.raises(MutationInactiveError):
            mutation.apply(apply_requested_by=superuser.email)

        assert mutation.status == inactive_status
        assert not mutation.is_active()


def test_append_mutation_application(superuser, redis, redis_string_key, default_value):
    """Test a APPEND mutation concatenates a value to a string."""
    append_value = "append-THIS"
    mutation = RedisMutation.objects.create(
        command=RedisMutation.MutationCommand.APPEND,
        redis_key=redis_string_key,
        value=append_value,
        redis_type=RedisMutation.RedisType.STRING,
        approval_threshold=1,
        status=RedisMutation.Status.CREATED,
    )
    mutation.approve(approved_by=superuser.email)
    mutation.apply(apply_requested_by=superuser.email)

    assert mutation.status == RedisMutation.Status.COMPLETED
    assert redis.get(redis_string_key).decode("utf-8") == default_value + append_value


def test_del_mutation_application(superuser, redis, redis_string_key):
    """Test a EXPIRE mutation removes a key from the database."""
    mutation = RedisMutation.objects.create(
        command=RedisMutation.MutationCommand.DEL,
        redis_key=redis_string_key,
        value=None,
        redis_type=RedisMutation.RedisType.STRING,
        approval_threshold=1,
        status=RedisMutation.Status.CREATED,
    )
    mutation.approve(approved_by=superuser.email)
    mutation.apply(apply_requested_by=superuser.email)

    assert mutation.status == RedisMutation.Status.COMPLETED
    assert redis.get(redis_string_key) is None


def test_expire_mutation_application(superuser, redis, redis_string_key):
    """Test a EXPIRE mutation sets a TTL to a key."""
    mutation = RedisMutation.objects.create(
        command=RedisMutation.MutationCommand.EXPIRE,
        redis_key=redis_string_key,
        value=10,
        redis_type=RedisMutation.RedisType.STRING,
        approval_threshold=1,
        status=RedisMutation.Status.CREATED,
    )
    mutation.approve(approved_by=superuser.email)
    mutation.apply(apply_requested_by=superuser.email)

    assert mutation.status == RedisMutation.Status.COMPLETED
    assert redis.ttl(redis_string_key) == 10


def test_lpush_mutation_application(superuser, redis, redis_list_key, default_value):
    """Test a LPUSH mutation appends a value to a list."""
    value = "an-lpushed-value"
    mutation = RedisMutation.objects.create(
        command=RedisMutation.MutationCommand.LPUSH,
        redis_key=redis_list_key,
        value=value,
        redis_type=RedisMutation.RedisType.LIST,
        approval_threshold=1,
        status=RedisMutation.Status.CREATED,
    )
    mutation.approve(approved_by=superuser.email)
    mutation.apply(apply_requested_by=superuser.email)

    assert mutation.status == RedisMutation.Status.COMPLETED
    assert redis.lrange(redis_list_key, 0, -1) == [value.encode("utf-8"), default_value.encode("utf-8")]


def test_lpush_tracks_error(superuser, redis, redis_string_key, default_value):
    """Test a LPUSH mutation will record an error on application."""
    new_value = "new-test-value"
    mutation = RedisMutation.objects.create(
        command=RedisMutation.MutationCommand.LPUSH,
        redis_key=redis_string_key,
        value=new_value,
        redis_type=RedisMutation.RedisType.LIST,
        approval_threshold=1,
        status=RedisMutation.Status.CREATED,
    )
    mutation.approve(approved_by=superuser.email)
    mutation.apply(apply_requested_by=superuser.email)

    assert mutation.status == RedisMutation.Status.FAILED
    assert redis.get(redis_string_key).decode("utf-8") == default_value
    # This should be validated in the form when creating the mutation, but here we interact with the database
    # directly thus bypass validation.
    assert mutation.apply_error == "ResponseError: WRONGTYPE Operation against a key holding the wrong kind of value"


def test_lset_mutation_application(superuser, redis, redis_list_key, default_value):
    """Test a LSET mutation appends a value to a list."""
    redis.rpush(redis_list_key, default_value)
    assert redis.lrange(redis_list_key, 0, -1) == [
        default_value.encode("utf-8"),
        default_value.encode("utf-8"),
    ]

    value_start = "a-value-set-at-start"
    mutation = RedisMutation.objects.create(
        command=RedisMutation.MutationCommand.LSET,
        redis_key=redis_list_key,
        value={"index": 0, "value": value_start},
        redis_type=RedisMutation.RedisType.LIST,
        approval_threshold=1,
        status=RedisMutation.Status.CREATED,
    )
    mutation.approve(approved_by=superuser.email)
    mutation.apply(apply_requested_by=superuser.email)

    assert mutation.status == RedisMutation.Status.COMPLETED, mutation.apply_error

    value_end = "a-value-set-at-end"
    mutation = RedisMutation.objects.create(
        command=RedisMutation.MutationCommand.LSET,
        redis_key=redis_list_key,
        value={"index": -1, "value": value_end},
        redis_type=RedisMutation.RedisType.LIST,
        approval_threshold=1,
        status=RedisMutation.Status.CREATED,
    )

    mutation.approve(approved_by=superuser.email)
    mutation.apply(apply_requested_by=superuser.email)

    assert mutation.status == RedisMutation.Status.COMPLETED, mutation.apply_error
    assert redis.lrange(redis_list_key, 0, -1) == [
        value_start.encode("utf-8"),
        value_end.encode("utf-8"),
    ]


def test_rpush_mutation_application(superuser, redis, redis_list_key, default_value):
    """Test a RPUSH mutation appends a value to a list."""
    value = "an-rpushed-value"
    mutation = RedisMutation.objects.create(
        command=RedisMutation.MutationCommand.RPUSH,
        redis_key=redis_list_key,
        value=value,
        redis_type=RedisMutation.RedisType.LIST,
        approval_threshold=1,
        status=RedisMutation.Status.CREATED,
    )
    mutation.approve(approved_by=superuser.email)
    mutation.apply(apply_requested_by=superuser.email)

    assert mutation.status == RedisMutation.Status.COMPLETED
    assert redis.lrange(redis_list_key, 0, -1) == [default_value.encode("utf-8"), value.encode("utf-8")]


def test_sadd_mutation_application(superuser, redis, redis_set_key, default_value):
    """Test a SADD mutation can be successfully applied."""
    sadd_value = "sadd-THIS"
    mutation = RedisMutation.objects.create(
        command=RedisMutation.MutationCommand.SADD,
        redis_key=redis_set_key,
        value=sadd_value,
        redis_type=RedisMutation.RedisType.SET,
        approval_threshold=1,
        status=RedisMutation.Status.CREATED,
    )
    mutation.approve(approved_by=superuser.email)
    mutation.apply(apply_requested_by=superuser.email)

    assert mutation.status == RedisMutation.Status.COMPLETED
    assert redis.smembers(redis_set_key) == {default_value.encode("utf-8"), sadd_value.encode("utf-8")}


def test_set_mutation_application(superuser, redis, redis_string_key):
    """Test a SET mutation can be successfully applied."""
    new_value = "new-test-value"
    mutation = RedisMutation.objects.create(
        command=RedisMutation.MutationCommand.SET,
        redis_key=redis_string_key,
        value=new_value,
        redis_type=RedisMutation.RedisType.STRING,
        approval_threshold=1,
        status=RedisMutation.Status.CREATED,
    )
    mutation.approve(approved_by=superuser.email)
    mutation.apply(apply_requested_by=superuser.email)

    assert mutation.status == RedisMutation.Status.COMPLETED
    assert redis.get(redis_string_key).decode("utf-8") == new_value


def test_set_mutation_failure_tracks_error(superuser, redis, redis_string_key, default_value):
    """Test error information is tracked on SET Redis mutation failure."""
    new_value = "new-test-value"
    mutation = RedisMutation.objects.create(
        command=RedisMutation.MutationCommand.SET,
        redis_key=redis_string_key,
        value=new_value,
        redis_type=RedisMutation.RedisType.STRING,
        approval_threshold=1,
        status=RedisMutation.Status.CREATED,
        optional_command_parameters={
            "ex": "a"
        },  # This is an invalid parameter that should be caught by form validation.
    )
    mutation.approve(approved_by=superuser.email)
    mutation.apply(apply_requested_by=superuser.email)

    assert mutation.status == RedisMutation.Status.FAILED
    assert redis.get(redis_string_key).decode("utf-8") == default_value
    assert mutation.apply_error == "DataError: ex must be datetime.timedelta or int"


def test_zadd_mutation_application(superuser, redis, redis_zset_key, default_value):
    """Test a ZADD mutation updates a ZSET with a new value."""
    value_key = "zadd-THIS-with-THIS-score"
    value_score = 999
    zadd_value = {value_key: value_score}
    mutation = RedisMutation.objects.create(
        command=RedisMutation.MutationCommand.ZADD,
        redis_key=redis_zset_key,
        value=zadd_value,
        redis_type=RedisMutation.RedisType.SET,
        approval_threshold=1,
        status=RedisMutation.Status.CREATED,
    )
    mutation.approve(approved_by=superuser.email)
    mutation.apply(apply_requested_by=superuser.email)

    assert mutation.status == RedisMutation.Status.COMPLETED, mutation.apply_error
    assert redis.zrange(redis_zset_key, 0, -1, withscores=True) == [
        (default_value.encode("utf-8"), 0),
        (value_key.encode("utf-8"), value_score),
    ]


def test_zincrby_mutation_application(superuser, redis, redis_zset_key, default_value):
    """Test a ZINCRBY mutation increments the score of the default value in a ZSET."""
    value_increment = 111
    zincrby_value = {"value": default_value, "amount": value_increment}
    mutation = RedisMutation.objects.create(
        command=RedisMutation.MutationCommand.ZINCRBY,
        redis_key=redis_zset_key,
        value=zincrby_value,
        redis_type=RedisMutation.RedisType.SET,
        approval_threshold=1,
        status=RedisMutation.Status.CREATED,
    )
    mutation.approve(approved_by=superuser.email)
    mutation.apply(apply_requested_by=superuser.email)

    assert mutation.status == RedisMutation.Status.COMPLETED, mutation.apply_error
    assert redis.zrange(redis_zset_key, 0, -1, withscores=True) == [
        (default_value.encode("utf-8"), value_increment),
    ]
