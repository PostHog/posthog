import datetime as dt

from django.contrib.postgres import fields
from django.db import models


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
        STRING = "string"
        HASH = "hash"
        ZSET = "zset"
        LIST = "list"
        SET = "set"

    class Status(models.TextChoices):
        CREATED = "created"
        APPROVED = "approved"
        COMPLETED = "applied"
        FAILED = "failed"
        DISCARDED = "discarded"

    class MutationCommand(models.TextChoices):
        SET = "set"
        APPEND = "append"
        EXPIRE = "expire"
        DEL = "del"
        ZADD = "zadd"
        SADD = "sadd"

    id = models.BigAutoField(primary_key=True, editable=False)

    redis_key = models.CharField(max_length=200, null=False, blank=False)
    redis_type = models.CharField(max_length=200, null=False, blank=False, choices=RedisType.choices)
    value = models.CharField(null=True, blank=True)
    command = models.CharField(max_length=200, null=False, blank=False, choices=MutationCommand.choices)
    parameters = models.JSONField(default=dict, blank=True)
    approval_threshold = models.IntegerField(null=False, default=2)

    status = models.CharField(
        max_length=200,
        null=False,
        choices=Status.choices,
        default=Status.CREATED,
    )
    approved_by = fields.ArrayField(base_field=models.CharField(null=False), default=list, editable=False)
    created_at = models.DateTimeField(null=False, auto_now_add=True, editable=False)
    last_approved_at = models.DateTimeField(null=True, editable=False)
    last_updated_at = models.DateTimeField(null=False, auto_now=True, editable=False)
    applied_by = models.CharField(max_length=200, null=True, editable=False)
    applied_at = models.DateTimeField(null=True, editable=False)
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
        except Exception:
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
        """Run this mutation on Redis."""
        # TODO: Actually run the mutation
        # Implementation will vary according to command.
        pass

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
