import subprocess
from typing import Optional

# In production images, the two functions below are overwritten by container-images-cd.yml


def get_git_commit() -> Optional[str]:
    """Return the short hash of the last commit.

    Example: get_git_commit() => "4ff54c8d"
    """
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode("utf-8").strip()
    except Exception:
        return None


def get_git_branch() -> Optional[str]:
    """Returns the symbolic name of the current active branch. Will return None in case of failure.

    Example: get_git_branch() => "master"
    """

    try:
        return (
            subprocess.check_output(["git", "rev-parse", "--symbolic-full-name", "--abbrev-ref", "HEAD"])
            .decode("utf-8")
            .strip()
        )
    except Exception:
        return None
