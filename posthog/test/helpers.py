import os


def runs_on_internal_pr() -> bool:
    """
    Returns True when tests are running for an internal PR or on master,
    and False for fork PRs.
    Defaults to True, so local runs are unaffected.
    """
    value = os.getenv("RUNS_ON_INTERNAL_PR")
    if value is None:
        return True
    return value.lower() in {"1", "true"}
