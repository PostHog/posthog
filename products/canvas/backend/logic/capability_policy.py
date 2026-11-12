"""Who may widen a canvas's declared capabilities."""

import dataclasses

from posthog.models.user import User

from products.canvas.backend.capabilities import capability_widening
from products.canvas.backend.facade.contracts import CanvasCapabilityWideningDenied
from products.canvas.backend.logic.records import widening_record
from products.canvas.backend.models import Canvas


def assert_may_set_capabilities(canvas: Canvas, user: User | None, before: dict | None, after: dict | None) -> None:
    """Raise CanvasCapabilityWideningDenied when `after` declares more than `before` and `user` did not create the canvas.

    A canvas whose creator is gone (`created_by` is null) cannot be widened by anyone.
    A `before` of None counts as empty, so a head that predates the capabilities snapshot
    refuses a non-creator's first declaration. An `after` of None means the target's
    capabilities are unknown, so only the creator may set it.

    Notebook widget canvases are exempt: the notebook that owns one authors its source on every
    save, and the notebook's own permissions decide who may do that.
    """
    if canvas.source_policy != Canvas.SOURCE_POLICY_STANDARD:
        return
    widening = capability_widening(before, after)
    if after is not None and not widening.widens:
        return
    if user is not None and canvas.created_by_id is not None and canvas.created_by_id == user.id:
        return
    record = widening_record(widening)
    raise CanvasCapabilityWideningDenied(record if after is not None else dataclasses.replace(record, widens=True))
