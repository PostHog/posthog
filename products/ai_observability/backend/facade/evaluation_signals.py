from collections.abc import Callable

from django.dispatch import Signal

evaluation_output_changed = Signal()


def connect_evaluation_output_changed(receiver: Callable[..., object], *, dispatch_uid: str) -> None:
    """``receiver`` gets ``team_id=`` after an evaluation is created or its output type or output config changes,
    once that save commits. A receiver that raises is logged and never fails the save."""
    evaluation_output_changed.connect(receiver, dispatch_uid=dispatch_uid)
