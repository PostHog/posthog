from typing import Any

# Set by the apply path, when an approved change request replays its own change.
APPROVAL_APPLY_KEY = "approval_apply"

# Set by a product, to declare a write as its own internal plumbing.
INTERNAL_WRITE_KEY = "approval_internal_write"


def internal_write_context() -> dict[str, bool]:
    """Mark a resource write as product-internal plumbing, which approval policies ignore.

    Merge the result into the serializer context of the write:

        FeatureFlagSerializer(data=..., context={**self.context, **internal_write_context()})

    Use this only for a resource that the product generates and owns, and that no person
    authored. An example is the feature flag a survey mints to track who dismissed it. Product
    code supplies every value in such a resource, so an approver has no human decision to
    review, and gating it only blocks the parent write.

    This is not a system write. The acting user still owns the row, and activity logging still
    attributes the change to them. Declare ``is_system`` instead when no user acts at all, such
    as in a Celery task — see ``posthog.api.utils.ServiceRequest``.

    Merge into a copy of the context. Never mutate the caller's dict: the same request can also
    carry a user-authored write, and that write must still reach the gate.
    """
    return {INTERNAL_WRITE_KEY: True}


def is_exempt_write(view_or_serializer: Any, request: Any) -> bool:
    """Decide whether a write skips the approval gate.

    This is the one place that answers that question. ``approval_gate`` calls it before it
    resolves a team, an organization, or a policy, so an exempt write costs no queries.
    """
    context = getattr(view_or_serializer, "context", None)
    if isinstance(context, dict):
        # An approver already accepted this change, and the apply path replays it through this
        # same serializer. A second gate here would block or duplicate it.
        if context.get(APPROVAL_APPLY_KEY):
            return True
        # `is True` so that a mock, or an attribute-forwarding proxy, cannot claim the exemption.
        if context.get(INTERNAL_WRITE_KEY) is True:
            return True

    # A system write has no acting user, and a change request needs a requester to attribute it
    # to. Only a request that declares itself takes this path — a merely user-less request, such
    # as a pre-auth HttpRequest, still engages the gate.
    if getattr(request, "is_system", False) is True:
        return True

    return False
