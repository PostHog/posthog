import datetime as dt

from django.contrib.postgres import fields
from django.db import models

from posthog.redis import get_client


class MissingApprovalError(Exception):
    """Exception raised when executing an operation without required amount of approvals."""

    def __init__(self, threshold: int, approvals: int):
        missing = threshold - approvals

        if missing == 1:
            super().__init__(f"Missing 1 approval to reach threshold of {threshold} approvals required for mutation")
        else:
            super().__init__(
                f"Missing {missing} approvals to reach threshold of {threshold} approvals required for mutation"
            )


class MutationInactiveError(Exception):
    """Exception raised when attempting to manipulate an inactive mutation."""

    def __init__(self):
        super().__init__(
            "Mutation is inactive as it was applied (successfully or unsuccessfully) or was discarded. It cannot be used further."
        )


class MutationFailedToSaveError(Exception):
    """Exception to group any other exceptions raised by calling save."""

    pass


class NotSupportedCommandError(Exception):
    """Exception raised when attempting to apply an unsupported command to a Redis key of a given type."""

    def __init__(self, redis_key: str, redis_type: str | None, command: str, value: dict | None):
        super().__init__(
            f"Command '{command.upper()}' is not supported on key '{redis_key}' of type '{redis_type}' with value '{value}'."
        )


class RedisMutation(models.Model):
    """Modelling mutation operations that can be applied on Redis.

    The intention behind this model execute mutations on Redis and keep track of mutatione executed. These
    mutations may require the input from multiple PostHog engineers, which is why there is an approval workflow
    built into the model. Before a mutation can be approved, it requires approval by at least 'approval_threshold'
    unique engineers, whose usernames are recorded in 'approved_by'.

    A mutation is defined by the following:
    * The Redis key we are mutating.
    * The command (or operation) we are running to mutate the value (i.e. SET, ZADD, or DEL).
    * Optionally, a value used by the mutation (not all commands need a value, for example DEL takes no value).
    * Optionally, additional parameters for a particular command.

    A mutation also has a status, which transitions as follows:

    .. mermaid::
      stateDiagram-v2
        [*] --> CREATED
        state is_approved <<choice>>
        CREATED --> is_approved
        is_approved --> APPROVED: if approvals >= threshold
        is_approved --> DISCARDED : if discarded
        state is_applied_successfully <<choice>>
        APPROVED --> is_applied_successfully
        is_applied_successfully --> COMPLETED: if apply successful
        is_applied_successfully --> FAILED: if apply unsuccessful
    """

    class RedisType(models.TextChoices):
        HASH = "hash"
        LIST = "list"
        SET = "set"
        STRING = "string"
        ZSET = "zset"

    class Status(models.TextChoices):
        APPROVED = "approved"
        COMPLETED = "applied"
        CREATED = "created"
        DISCARDED = "discarded"
        FAILED = "failed"

    class MutationCommand(models.TextChoices):
        APPEND = "append"
        DEL = "del"
        EXPIRE = "expire"
        HSET = "hset"
        LPUSH = "lpush"
        LSET = "lset"
        RPUSH = "rpush"
        SADD = "sadd"
        SET = "set"
        ZADD = "zadd"
        ZINCRBY = "zincrby"

    id = models.BigAutoField(primary_key=True, editable=False)

    redis_key = models.CharField(max_length=200, null=False, blank=False)
    redis_type = models.CharField(max_length=200, null=True, blank=False, choices=RedisType.choices)
    value = models.JSONField(
        null=True,
        blank=True,
        help_text="JSON encoded mapping with value or values used in the mutation",
    )
    command = models.CharField(max_length=200, null=False, blank=False, choices=MutationCommand.choices)
    optional_command_parameters = models.JSONField(default=dict, blank=True)
    approval_threshold = models.IntegerField(null=False, default=2)

    status = models.CharField(
        max_length=200,
        null=False,
        choices=Status.choices,
    )
    approved_by = fields.ArrayField(base_field=models.CharField(null=False), default=list, editable=False)
    created_at = models.DateTimeField(null=False, auto_now_add=True, editable=False)
    last_approved_at = models.DateTimeField(null=True, editable=False)
    last_updated_at = models.DateTimeField(null=False, auto_now=True, editable=False)
    applied_by = models.CharField(max_length=200, null=True, editable=False)
    applied_at = models.DateTimeField(null=True, editable=False)
    apply_error = models.TextField(null=True, editable=False)
    discarded_by = models.CharField(max_length=200, null=True, editable=False)
    discarded_at = models.DateTimeField(null=True, editable=False)

    @property
    def approvals(self) -> int:
        """Return number of approvals on this mutation."""
        return len(self.approved_by)

    def apply(self, apply_requested_by: str):
        """Apply this mutation on Redis.

        Mutations can only be applied once: After attempting to run the mutation command, the mutation
        will be moved to an inactive state (FAILED or COMPLETED), and may not be used further. However,
        if we don't run the mutation command (due to an error before running the command), then the
        mutation can still be used and an apply may be attempted again after errors are addressed.

        Raises:
            MutationInactiveError: If attempting to apply an inactive mutation.
            MissingApprovalError: If attempting to apply a mutation without necessary number of approvals.
        """
        self.raise_if_not_active()

        if self.status != self.Status.APPROVED:
            raise MissingApprovalError(self.approval_threshold, self.approvals)

        try:
            self.run_mutation_command()
        except Exception as e:
            self.apply_error = f"{e.__class__.__name__}: {str(e)}"
            self.status = self.Status.FAILED
        else:
            self.status = self.Status.COMPLETED

        self.applied_by = apply_requested_by
        self.applied_at = dt.datetime.now()

        self.try_save()

    def raise_if_not_active(self) -> None:
        """Raise an exception if this mutation is not active."""
        if not self.is_active():
            raise MutationInactiveError()

    def is_active(self) -> bool:
        """Whether this mutation is still active and may still be approved and applied."""
        return self.status not in (self.Status.FAILED, self.Status.COMPLETED, self.Status.DISCARDED)

    def try_save(self):
        """Attempt to save mutation.

        Any exception raised as the cause for MutationFailedToSaveError so that callers can catch
        a single exception.
        """
        try:
            self.save()
        except Exception as e:
            raise MutationFailedToSaveError from e

    def run_mutation_command(self):
        """Run this mutation on Redis.

        Any new supported commands must be added here with their own unique implementation.
        """
        match (self.command, self.value):
            case (self.MutationCommand.APPEND, str(value)):
                redis_client = get_client()
                redis_client.append(self.redis_key, value, **self.optional_command_parameters)

            case (self.MutationCommand.DEL, _):
                redis_client = get_client()
                redis_client.delete(self.redis_key)

            case (self.MutationCommand.EXPIRE, int(seconds)):
                redis_client = get_client()
                redis_client.expire(self.redis_key, time=seconds)

            case (self.MutationCommand.HSET, dict(mapping)):
                redis_client = get_client()
                redis_client.hset(self.redis_key, mapping=mapping, **self.optional_command_parameters)

            case (self.MutationCommand.LPUSH, str(value)):
                redis_client = get_client()
                redis_client.lpush(self.redis_key, value)

            case (self.MutationCommand.LSET, {"index": int(index), "value": str(value)}):
                redis_client = get_client()
                redis_client.lset(self.redis_key, index, value)

            case (self.MutationCommand.RPUSH, str(value)):
                redis_client = get_client()
                redis_client.rpush(self.redis_key, value)

            case (self.MutationCommand.SADD, str(value)):
                # TODO: Support multiple members with one SADD, maybe by splitting comma/space?
                redis_client = get_client()
                redis_client.sadd(self.redis_key, value)

            case (self.MutationCommand.SET, str(value)):
                # We do not need to check here whether current type is 'string' as SET will overwrite
                # whatever value the key holds, regardless of its current type.
                # TODO: A warning could be issued if an overwrite to a non-string type happens.
                redis_client = get_client()
                redis_client.set(self.redis_key, value, **self.optional_command_parameters)

            case (self.MutationCommand.ZADD, dict(mapping)):
                # TODO: Support multiple members with one ZADD, maybe JSON encoding self.value?
                redis_client = get_client()
                redis_client.zadd(self.redis_key, mapping, **self.optional_command_parameters)

            case (self.MutationCommand.ZINCRBY, {"amount": int(amount), "value": str(value)}):
                redis_client = get_client()
                redis_client.zincrby(self.redis_key, amount, value)

            case _:
                raise NotSupportedCommandError(self.redis_key, self.redis_type, self.command, self.value)

    def discard(self, discarded_by: str) -> None:
        """Discard this active mutation."""
        self.raise_if_not_active()

        self.status = self.Status.DISCARDED
        self.discarded_by = discarded_by
        self.discarded_at = dt.datetime.now()

        self.try_save()

    def approve(self, approved_by: str) -> None:
        """Approve this active mutation.

        We allow multiple calls to 'approve' with the same 'approved_by'. However, approvals are
        unique, so only one call will be saved to the model.
        """
        self.raise_if_not_active()

        if approved_by in self.approved_by:
            return

        self.approved_by.append(approved_by)
        self.last_approved_at = dt.datetime.now()

        if self.is_over_approval_threshold():
            self.status = self.Status.APPROVED

        self.try_save()

    def is_over_approval_threshold(self) -> int:
        """Whether this mutation has enough approvals to be applied."""
        return self.approvals >= self.approval_threshold
