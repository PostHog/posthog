import pytest

from posthog.api.test.test_organization import create_organization
from posthog.models import RedisMutation, User
from posthog.models.redis import MutationInactiveError
from posthog.redis import get_client

pytestmark = [pytest.mark.django_db]


@pytest.fixture
def superuser():
    organization = create_organization("Test Org")
    superuser = User.objects.create_and_join(organization, "test@posthog.com", "abcde12345", is_staff=True)
    return superuser


@pytest.fixture
def redis():
    return get_client()


def test_mutation_can_be_approved(superuser):
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


def test_mutation_can_be_discarded(superuser):
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


def test_set_mutation_application(superuser, redis):
    """Test a SET mutation can be successfully applied."""
    key = "a-set-test-key"
    default_value = "a-default-value"
    redis.set(key, default_value)

    new_value = "new-test-value"
    mutation = RedisMutation.objects.create(
        command=RedisMutation.MutationCommand.SET,
        redis_key=key,
        value=new_value,
        redis_type=RedisMutation.RedisType.STRING,
        approval_threshold=1,
        status=RedisMutation.Status.CREATED,
    )
    mutation.approve(approved_by=superuser.email)
    mutation.apply(apply_requested_by=superuser.email)

    assert mutation.status == RedisMutation.Status.COMPLETED
    assert redis.get(key).decode("utf-8") == new_value


def test_set_mutation_failure_tracks_error(superuser, redis):
    """Test error information is tracked on SET Redis mutation failure."""
    key = "a-set-test-key"
    default_value = "a-default-value"
    redis.set(key, default_value)

    new_value = "new-test-value"
    mutation = RedisMutation.objects.create(
        command=RedisMutation.MutationCommand.SET,
        redis_key=key,
        value=new_value,
        redis_type=RedisMutation.RedisType.STRING,
        approval_threshold=1,
        status=RedisMutation.Status.CREATED,
        parameters={"ex": "a"},  # This is an invalid parameter that should be caught by form validation.
    )
    mutation.approve(approved_by=superuser.email)
    mutation.apply(apply_requested_by=superuser.email)

    assert mutation.status == RedisMutation.Status.FAILED
    assert redis.get(key).decode("utf-8") == default_value
    assert mutation.apply_error == "DataError: ex must be datetime.timedelta or int"


def test_append_mutation_application(superuser, redis):
    """Test a APPEND mutation can be successfully applied."""
    key = "a-append-test-key"
    default_value = "a-default-value"
    redis.set(key, default_value)

    append_value = "append-THIS"
    mutation = RedisMutation.objects.create(
        command=RedisMutation.MutationCommand.APPEND,
        redis_key=key,
        value=append_value,
        redis_type=RedisMutation.RedisType.STRING,
        approval_threshold=1,
        status=RedisMutation.Status.CREATED,
    )
    mutation.approve(approved_by=superuser.email)
    mutation.apply(apply_requested_by=superuser.email)

    assert mutation.status == RedisMutation.Status.COMPLETED
    assert redis.get(key).decode("utf-8") == default_value + append_value


def test_del_mutation_application(superuser, redis):
    """Test a DEL mutation can be successfully applied."""
    key = "a-del-test-key"
    default_value = "a-default-value"
    redis.set(key, default_value)

    mutation = RedisMutation.objects.create(
        command=RedisMutation.MutationCommand.DEL,
        redis_key=key,
        value=None,
        redis_type=RedisMutation.RedisType.STRING,
        approval_threshold=1,
        status=RedisMutation.Status.CREATED,
    )
    mutation.approve(approved_by=superuser.email)
    mutation.apply(apply_requested_by=superuser.email)

    assert mutation.status == RedisMutation.Status.COMPLETED
    assert redis.get(key) is None


def test_sadd_mutation_application(superuser, redis):
    """Test a SADD mutation can be successfully applied."""
    key = "an-sadd-test-key"
    value = "a-sadd-test-value"
    redis.sadd(key, value)

    sadd_value = "sadd-THIS"
    mutation = RedisMutation.objects.create(
        command=RedisMutation.MutationCommand.SADD,
        redis_key=key,
        value=sadd_value,
        redis_type=RedisMutation.RedisType.SET,
        approval_threshold=1,
        status=RedisMutation.Status.CREATED,
    )
    mutation.approve(approved_by=superuser.email)
    mutation.apply(apply_requested_by=superuser.email)

    assert mutation.status == RedisMutation.Status.COMPLETED
    assert redis.smembers(key) == {b"a-sadd-test-value", b"sadd-THIS"}
