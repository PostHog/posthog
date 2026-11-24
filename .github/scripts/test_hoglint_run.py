import re
import tomllib
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
REPO_ROOT = SCRIPTS_DIR.parent.parent


def pep723_pins(script_text: str) -> dict[str, str]:
    match = re.search(r"^# dependencies = \[(.*)\]$", script_text, re.MULTILINE)
    assert match is not None, "hoglint_run.py must declare its dependencies in one PEP 723 line"
    pins = dict(re.findall(r'"([a-z0-9-]+)==([^"]+)"', match.group(1)))
    assert set(pins) == {"hoglint", "django"}, "hoglint_run.py must pin exactly hoglint and django"
    return pins


def dev_group_hoglint_pin(pyproject_text: str) -> str:
    dev = tomllib.loads(pyproject_text)["dependency-groups"]["dev"]
    pins = [
        entry.removeprefix("hoglint==") for entry in dev if isinstance(entry, str) and entry.startswith("hoglint==")
    ]
    assert len(pins) == 1, "the dev group of pyproject.toml must pin hoglint once, as hoglint==<version>"
    return pins[0]


def locked_version(lock_text: str, name: str) -> str:
    versions = [package["version"] for package in tomllib.loads(lock_text)["package"] if package["name"] == name]
    assert len(versions) == 1, f"uv.lock must lock {name} once"
    return versions[0]


def test_hoglint_run_pins_the_dev_group_hoglint_version() -> None:
    pinned = pep723_pins((SCRIPTS_DIR / "hoglint_run.py").read_text())["hoglint"]
    dev = dev_group_hoglint_pin((REPO_ROOT / "pyproject.toml").read_text())
    assert pinned == dev, (
        f"hoglint_run.py pins hoglint=={pinned} but pyproject.toml's dev group pins hoglint=={dev}; "
        "bump both together so the answers come from the hoglint that `hoglint compare` runs"
    )


def test_hoglint_run_pins_the_locked_django_version() -> None:
    pinned = pep723_pins((SCRIPTS_DIR / "hoglint_run.py").read_text())["django"]
    locked = locked_version((REPO_ROOT / "uv.lock").read_text(), "django")
    assert pinned == locked, (
        f"hoglint_run.py pins django=={pinned} but uv.lock locks django=={locked}; "
        "hoglint reads the repo's models through this Django, so keep them equal"
    )
