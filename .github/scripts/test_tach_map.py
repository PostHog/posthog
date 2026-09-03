import re
import tomllib
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
REPO_ROOT = SCRIPTS_DIR.parent.parent


def pep723_tach_pin(script_text: str) -> str:
    match = re.search(r'^# dependencies = \[\s*"tach==([^"]+)"\s*\]', script_text, re.MULTILINE)
    assert match is not None, "tach_map.py must pin exactly one dependency, tach==<version>"
    return match.group(1)


def locked_tach_version(lock_text: str) -> str:
    packages = tomllib.loads(lock_text)["package"]
    return next(package["version"] for package in packages if package["name"] == "tach")


def test_tach_map_pins_the_locked_tach_version() -> None:
    pinned = pep723_tach_pin((SCRIPTS_DIR / "tach_map.py").read_text())
    locked = locked_tach_version((REPO_ROOT / "uv.lock").read_text())
    assert pinned == locked, (
        f"tach_map.py pins tach=={pinned} but uv.lock resolves tach=={locked}; "
        "bump the PEP 723 pin so the import map comes from the tach that `tach check` runs"
    )
