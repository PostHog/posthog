import importlib
from pathlib import Path

import posthog.egress
from posthog.egress.limiter.policies import Priority, resolve_policy

_EGRESS_ROOT = Path(posthog.egress.__file__).parent

_FLAT_DOMAINS = {"google_workspace"}


def _domain_dirs() -> list[Path]:
    return sorted(path.parent for path in _EGRESS_ROOT.glob("*/transport.py") if path.parent.name != "transport")


def test_every_domain_documents_itself_in_a_readme() -> None:
    missing = [domain.name for domain in _domain_dirs() if not (domain / "README.md").is_file()]
    assert missing == []


def test_only_reviewed_domains_run_a_flat_policy() -> None:
    # Resolving by directory name, not scanning the registry, ignores flat policies other modules register.
    flat = set()
    for domain in _domain_dirs():
        if not (domain / "limiter.py").is_file():
            continue
        importlib.import_module(f"posthog.egress.{domain.name}.limiter")
        if resolve_policy(f"{domain.name}:scope:1").reserve_fraction(Priority.BATCH) == 0.0:
            flat.add(domain.name)
    assert flat == _FLAT_DOMAINS
