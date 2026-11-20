import re
import tomllib
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
REPO_ROOT = SCRIPTS_DIR.parent.parent


def pep723_hoglint_pin(script_text: str) -> str:
    match = re.search(r'^# dependencies = \[\s*"hoglint==([^"]+)"\s*\]', script_text, re.MULTILINE)
    assert match is not None, "hoglint_map.py must pin exactly one dependency, hoglint==<version>"
    return match.group(1)


def dev_group_hoglint_pin(pyproject_text: str) -> str:
    dev = tomllib.loads(pyproject_text)["dependency-groups"]["dev"]
    pins = [
        entry.removeprefix("hoglint==") for entry in dev if isinstance(entry, str) and entry.startswith("hoglint==")
    ]
    assert len(pins) == 1, "the dev group of pyproject.toml must pin hoglint once, as hoglint==<version>"
    return pins[0]


def test_hoglint_map_pins_the_dev_group_hoglint_version() -> None:
    pinned = pep723_hoglint_pin((SCRIPTS_DIR / "hoglint_map.py").read_text())
    dev = dev_group_hoglint_pin((REPO_ROOT / "pyproject.toml").read_text())
    assert pinned == dev, (
        f"hoglint_map.py pins hoglint=={pinned} but pyproject.toml's dev group pins hoglint=={dev}; "
        "bump both together so the import map comes from the hoglint that `hoglint compare` runs"
    )
