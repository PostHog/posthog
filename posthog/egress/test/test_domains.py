import importlib
from pathlib import Path

import posthog.egress
from posthog.egress.limiter.policies import _REGISTRY, Priority, resolve_policy

_EGRESS_ROOT = Path(posthog.egress.__file__).parent

_FLAT_DOMAINS = {"google_workspace"}


def _domain_dirs() -> list[Path]:
    return sorted(path.parent for path in _EGRESS_ROOT.glob("*/transport.py") if path.parent.name != "transport")


def _cites_sources(readme: Path) -> bool:
    if not readme.is_file():
        return False
    _, _, sources = readme.read_text().partition("\n## Sources\n")
    return "https://" in sources


def test_every_domain_documents_itself_in_a_readme_with_sources() -> None:
    missing = [domain.name for domain in _domain_dirs() if not _cites_sources(domain / "README.md")]
    assert missing == []


def test_only_reviewed_domains_run_a_flat_policy() -> None:
    domain_names = {domain.name for domain in _domain_dirs()}
    for domain in _domain_dirs():
        if (domain / "limiter.py").is_file():
            importlib.import_module(f"posthog.egress.{domain.name}.limiter")

    # A domain registers under its directory name or a `<name>_` prefix (GitHub's search meters), which
    # leaves out the flat policies that modules outside egress register in the same test run.
    flat = {
        name
        for name in _REGISTRY
        if any(name == domain or name.startswith(f"{domain}_") for domain in domain_names)
        and resolve_policy(f"{name}:scope:1").reserve_fraction(Priority.BATCH) == 0.0
    }
    assert flat == _FLAT_DOMAINS
