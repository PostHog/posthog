import os
import math
import time
import random
import statistics
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from functools import partial
from typing import cast
from uuid import uuid4

from unittest.mock import patch

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from posthog import redis
from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User

from products.access_control.backend.facade.user_access_control import ACCESS_CONTROL_RESOURCES
from products.access_control.backend.models.access_control import AccessControl
from products.authz.backend.bootstrap import bootstrap_openfga
from products.authz.backend.client import Consistency, close_cached_openfga_client, get_openfga_client
from products.authz.backend.facade import api
from products.authz.backend.facade.contracts import CheckRequest, Context, Resource, Subject
from products.authz.backend.facade.enums import Action, ResourceType
from products.authz.backend.logic import authorization, legacy_authorization, sync_state
from products.authz.backend.logic.rollout import RolloutMode
from products.dashboards.backend.models.dashboard import Dashboard

ROLLOUT_MODES: tuple[RolloutMode, ...] = ("v1", "v1-shadow-log", "v2")


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise ValueError("Value must be positive")
    return number


def percentile(samples: Sequence[float], fraction: float) -> float:
    ordered = sorted(samples)
    rank = (len(ordered) - 1) * fraction
    lower = math.floor(rank)
    upper = math.ceil(rank)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def _discard_log(*_args: object, **_kwargs: object) -> None:
    return


def summarize(samples: list[float]) -> dict[str, float]:
    return {
        "mean": statistics.mean(samples),
        "median": statistics.median(samples),
        "stddev": statistics.stdev(samples) if len(samples) > 1 else 0.0,
        "p90": percentile(samples, 0.9),
        "p95": percentile(samples, 0.95),
        "p99": percentile(samples, 0.99),
    }


@contextmanager
def measure_checkers(consistency: Consistency) -> Iterator[dict[str, float]]:
    elapsed_ms: dict[str, float] = {}

    def measure(
        name: str, checker: Callable[[Sequence[CheckRequest], Context | None], list[bool]]
    ) -> Callable[[Sequence[CheckRequest], Context | None], list[bool]]:
        def measured(requests: Sequence[CheckRequest], context: Context | None) -> list[bool]:
            started = time.perf_counter_ns()
            try:
                return checker(requests, context)
            finally:
                elapsed_ms[name] = elapsed_ms.get(name, 0.0) + (time.perf_counter_ns() - started) / 1_000_000

        return measured

    with (
        patch.object(authorization, "check", measure("OpenFGA", partial(authorization.check, consistency=consistency))),
        patch.object(legacy_authorization, "check", measure("Legacy", legacy_authorization.check)),
    ):
        yield elapsed_ms


class Command(BaseCommand):
    help = "Create temporary benchmark data and compare authorization rollout modes."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--resource-type", choices=(ResourceType.DASHBOARD.value, ResourceType.INSIGHT.value), default="dashboard"
        )
        parser.add_argument(
            "--action",
            choices=(
                Action.VIEW.value,
                Action.EDIT.value,
                Action.DELETE.value,
                Action.SHARE.value,
                Action.MANAGE_ACCESS.value,
                Action.CREATE.value,
            ),
            default=Action.VIEW.value,
        )
        parser.add_argument("--requests", type=positive_int, default=200_000)
        parser.add_argument("--batch-size", type=positive_int, default=100)
        parser.add_argument("--warmup-batches", type=int, default=5)
        parser.add_argument(
            "--consistency", choices=("MINIMIZE_LATENCY", "HIGHER_CONSISTENCY"), default="MINIMIZE_LATENCY"
        )
        parser.add_argument("--mode", choices=ROLLOUT_MODES, action="append", dest="modes")

    def handle(self, *args: object, **options: object) -> None:
        if not settings.DEBUG:
            raise CommandError("Run this benchmark only with DEBUG enabled.")

        total_requests = cast(int, options["requests"])
        batch_size = cast(int, options["batch_size"])
        warmup_batches = cast(int, options["warmup_batches"])
        consistency = cast(Consistency, options["consistency"])
        if warmup_batches < 0:
            raise CommandError("Warmup batch count cannot be negative")

        modes = cast(list[RolloutMode] | None, options["modes"]) or list(ROLLOUT_MODES)
        modes = list(dict.fromkeys(modes))
        store_name = f"authz-benchmark-{uuid4()}"

        with patch.dict(os.environ, {"OPENFGA_STORE_NAME": store_name}):
            os.environ.pop("OPENFGA_STORE_ID", None)
            os.environ.pop("OPENFGA_AUTHORIZATION_MODEL_ID", None)
            with transaction.atomic():
                organization: Organization | None = None
                try:
                    organization = Organization.objects.create(name=f"Authorization benchmark {uuid4()}")
                    organization.available_product_features = [
                        {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
                    ]
                    organization.save()
                    team = Team.objects.create(organization=organization, name="Authorization benchmark")
                    user = User.objects.create_and_join(
                        organization,
                        f"authz-benchmark-{uuid4()}@example.com",
                        password=None,
                        level=OrganizationMembership.Level.OWNER,
                    )
                    benchmark_users = [
                        User.objects.create_and_join(
                            organization,
                            f"authz-benchmark-{uuid4()}@example.com",
                            password=None,
                            level=OrganizationMembership.Level.MEMBER,
                        )
                        for _ in range(20)
                    ]
                    memberships = {
                        member.user_id: member
                        for member in OrganizationMembership.objects.filter(
                            organization=organization, user__in=benchmark_users
                        )
                    }
                    dashboards = Dashboard.objects.bulk_create(
                        [Dashboard(team=team, created_by=user) for _ in range(20)]
                    )
                    dashboard_ids = [str(dashboard.id) for dashboard in dashboards]

                    rng = random.Random(0)
                    candidates: list[tuple[OrganizationMembership, str, str | None]] = [
                        (member, resource, None)
                        for member in memberships.values()
                        for resource in ACCESS_CONTROL_RESOURCES
                    ]
                    candidates.extend(
                        (member, "dashboard", dashboard_id)
                        for member in memberships.values()
                        for dashboard_id in dashboard_ids
                    )
                    rng.shuffle(candidates)
                    AccessControl.objects.bulk_create(
                        [
                            AccessControl(
                                team=team,
                                organization_member=member,
                                resource=resource,
                                resource_id=resource_id,
                                access_level=rng.choice(("none", "viewer", "editor", "manager")),
                                created_by=user,
                            )
                            for member, resource, resource_id in candidates
                        ]
                    )

                    resource_type = ResourceType(cast(str, options["resource_type"]))
                    action = Action(cast(str, options["action"]))
                    request_pool = [
                        CheckRequest(
                            resource=Resource(
                                type=resource_type,
                                id=dashboard_id if resource_type == ResourceType.DASHBOARD else None,
                                project_id=team.id,
                                organization_id=organization.id,
                            ),
                            action=action,
                            subject=Subject(user_id=member.id),
                        )
                        for member in benchmark_users
                        for dashboard_id in (
                            [None] * 10 + dashboard_ids if resource_type == ResourceType.DASHBOARD else [None]
                        )
                    ]
                    model_id = bootstrap_openfga()
                    os.environ["OPENFGA_AUTHORIZATION_MODEL_ID"] = model_id
                    api.synchronize_organization(organization.id)

                    self.stdout.write("Authorization benchmark")
                    self.stdout.write(f"Checks per mode: {total_requests:,}; batch size: {batch_size:,}")
                    self.stdout.write("Temporary database data and the OpenFGA store are removed after the run.")
                    self.stdout.write("Rollout mode is overridden in-process. No feature flag setting is changed.")
                    self.stdout.write(
                        "v1 runs legacy checks. v1-shadow-log runs both checkers; comparison logs are suppressed."
                    )
                    self.stdout.write("v2 uses OpenFGA for decisions and runs legacy checks for comparison.")
                    self.stdout.write(f"OpenFGA consistency: {consistency}.")
                    self.stdout.write("Latency is batch wall time divided by checks; percentiles summarize batches.")
                    self.stdout.write(
                        "Component timings include each checker's scope lookups, SDK calls, and readiness checks."
                    )
                    self.stdout.write("")

                    summaries: dict[str, dict[str, float]] = {}
                    allowed_counts: dict[str, int] = {}
                    for mode in modes:
                        samples: list[float] = []
                        component_samples: dict[str, list[float]] = {}
                        elapsed_seconds = 0.0
                        allowed_count = 0
                        batches = math.ceil(total_requests / batch_size)
                        with (
                            patch("products.authz.backend.logic.rollout.get_feature_flag_or_none", return_value=mode),
                            patch("products.authz.backend.logic.rollout.logger.info", _discard_log),
                        ):
                            rng = random.Random(1)
                            for batch_number in range(warmup_batches + batches):
                                measured_batch = batch_number - warmup_batches
                                count = (
                                    min(batch_size, total_requests - measured_batch * batch_size)
                                    if measured_batch >= 0
                                    else batch_size
                                )
                                checks = [rng.choice(request_pool) for _ in range(count)]
                                with api.authorization_session(), measure_checkers(consistency) as components:
                                    started = time.perf_counter_ns()
                                    decisions = api.check(checks)
                                    elapsed = (time.perf_counter_ns() - started) / 1_000_000
                                if measured_batch >= 0:
                                    elapsed_seconds += elapsed / 1000
                                    samples.append(elapsed / count)
                                    for name, component_elapsed in components.items():
                                        component_samples.setdefault(name, []).append(component_elapsed / count)
                                    allowed_count += sum(decisions)

                        summary = summarize(samples)
                        summary["throughput"] = total_requests / elapsed_seconds
                        summaries[mode] = summary
                        allowed_counts[mode] = allowed_count
                        self.stdout.write(
                            f"{mode}: {allowed_count:,}/{total_requests:,} allowed | "
                            f"mean {summary['mean']:.4f} ms | median {summary['median']:.4f} ms | "
                            f"std dev {summary['stddev']:.4f} ms | p90 {summary['p90']:.4f} ms | "
                            f"p95 {summary['p95']:.4f} ms | p99 {summary['p99']:.4f} ms | "
                            f"{summary['throughput']:,.0f} checks/s"
                        )

                        if mode != "v1":
                            for name, component in component_samples.items():
                                timing = summarize(component)
                                label = (
                                    "OpenFGA-only"
                                    if name == "OpenFGA"
                                    else "Legacy comparison"
                                    if mode == "v2"
                                    else "Legacy primary"
                                )
                                self.stdout.write(
                                    f"  {label}: mean {timing['mean']:.4f} ms | median {timing['median']:.4f} ms | "
                                    f"p95 {timing['p95']:.4f} ms | p99 {timing['p99']:.4f} ms"
                                )

                    baseline = summaries.get("v1")
                    if baseline is not None:
                        self.stdout.write("")
                        for mode in modes:
                            if mode == "v1":
                                continue
                            summary = summaries[mode]
                            change = (summary["mean"] / baseline["mean"] - 1) * 100 if baseline["mean"] else 0
                            direction = "faster" if change < 0 else "slower" if change > 0 else "the same"
                            self.stdout.write(f"{mode} mean latency: {abs(change):.1f}% {direction} than v1.")

                    if len(set(allowed_counts.values())) > 1:
                        self.stdout.write(
                            self.style.WARNING("Authorization decisions differ between the measured modes.")
                        )
                finally:
                    try:
                        if organization is not None:
                            redis.get_client().delete(sync_state.state_key(organization.id))
                    finally:
                        client = get_openfga_client()
                        try:
                            if client.get_store_id() is not None:
                                client.delete_store()
                        finally:
                            client.close()
                            close_cached_openfga_client()
                        transaction.set_rollback(True)
