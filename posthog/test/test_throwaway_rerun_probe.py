import os


def test_throwaway_rerun_probe() -> None:
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT")
    assert os.environ.get("THROWAWAY_RERUN_TOGGLE") == "pass", f"GITHUB_RUN_ATTEMPT={attempt!r}"
