from collections import Counter
from collections.abc import Callable
from typing import Any

from django.core.checks.registry import registry

from posthog.checks import CHECK_ID_PATTERN

OWNED_PACKAGES = ("posthog", "ee", "products", "common")


def _owned_checks() -> list[Callable[..., Any]]:
    checks = registry.get_checks(include_deployment_checks=True)
    return [check for check in checks if check.__module__.split(".")[0] in OWNED_PACKAGES]


def _label(check: Callable[..., Any]) -> str:
    return f"{check.__module__}.{check.__qualname__}"


def test_every_system_check_declares_ids_in_the_posthog_scheme() -> None:
    checks = _owned_checks()
    assert checks, "No PostHog system check is registered, so this test checks nothing."

    problems: list[str] = []
    for check in checks:
        check_ids: tuple[str, ...] = getattr(check, "check_ids", ())
        if not check_ids:
            problems.append(f"{_label(check)} declares no IDs. Register it with posthog.checks.register_check.")
        for check_id in check_ids:
            if not CHECK_ID_PATTERN.match(check_id):
                problems.append(f"{_label(check)} emits {check_id!r}, which is not posthog.<area>.<E|W><nnn>.")
        module_parts = check.__module__.split(".")
        if module_parts[0] == "products":
            prefix = f"posthog.{module_parts[1]}."
            problems.extend(
                f"{_label(check)} emits {check_id!r}, but a product check must start with {prefix!r}."
                for check_id in check_ids
                if not check_id.startswith(prefix)
            )

    assert not problems, "\n".join(problems)


def test_system_check_ids_are_unique() -> None:
    counts = Counter(check_id for check in _owned_checks() for check_id in getattr(check, "check_ids", ()))
    duplicates = sorted(check_id for check_id, count in counts.items() if count > 1)
    assert not duplicates, f"These system check IDs are declared by more than one check: {duplicates}"
