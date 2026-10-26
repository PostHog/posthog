from contextlib import ExitStack
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.utils import absolute_uri

from products.alerts_platform.backend.delivery import delivery_paths, describers, legacy_webhook
from products.alerts_platform.backend.delivery.destinations import list_alert_destination_groups
from products.alerts_platform.backend.delivery.evaluation import LIVE_DELIVERY_FLAG, deliver_evaluation
from products.alerts_platform.backend.delivery.legacy_webhook import LEGACY_WEBHOOK_BODY_FLAG
from products.alerts_platform.backend.delivery.message import AlertMessage
from products.alerts_platform.backend.delivery.thread_store import ThreadBusy
from products.alerts_platform.backend.delivery.transport import DeliveryError, MessageHandle
from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertDestinationData,
    AlertDestinationGroup,
    AlertEventKind,
    AnnouncedTransition,
    DeliveryPath,
    DestinationType,
    EvaluationAnnouncement,
    IncidentAction,
    LegacyEventEmission,
    MessageLink,
    SourceKind,
)
from products.alerts_platform.backend.models import PlatformAlertConfiguration
from products.alerts_platform.backend.tests.recorded_metrics import recorded_metrics

_MODULE = "products.alerts_platform.backend.delivery.evaluation"
_LEGACY_MODULE = "products.alerts_platform.backend.delivery.legacy_webhook"
_WEBHOOK_URL_MODULE = "products.alerts_platform.backend.delivery.webhook_url"
FIRING = datetime(2026, 9, 30, 9, tzinfo=UTC)

FIRING_EVENT = "$logs_alert_firing"
RESOLVED_EVENT = "$logs_alert_resolved"
OPENED_EVENT = "$logs_alert_incident_opened"
CLOSED_EVENT = "$logs_alert_incident_closed"

SLACK = cast(AlertDestinationData, {"type": DestinationType.SLACK, "slack_workspace_id": 1, "slack_channel_id": "C-1"})
WEBHOOK = cast(AlertDestinationData, {"type": DestinationType.WEBHOOK, "webhook_url": "https://example.com/hook"})
SECOND_WEBHOOK = cast(
    AlertDestinationData, {"type": DestinationType.WEBHOOK, "webhook_url": "https://example.com/other"}
)
TEAMS = cast(AlertDestinationData, {"type": DestinationType.TEAMS, "webhook_url": "https://example.com/teams"})
PAGERDUTY = cast(AlertDestinationData, {"type": DestinationType.PAGERDUTY, "pagerduty_routing_key": "R-1"})
UNSUPPORTED = cast(AlertDestinationData, {"type": "opsgenie"})
HOG_FUNCTION_SLACK = AlertDestinationGroup(
    hog_function_ids=(UUID("01900000-0000-0000-0000-0000000000a1"),), data=SLACK, fully_enabled=True
)
SUBSCRIBER = AlertDestinationGroup(
    hog_function_ids=(),
    data=cast(
        AlertDestinationData, {"type": DestinationType.SLACK, "slack_workspace_id": 1, "slack_channel_id": "C-2"}
    ),
    fully_enabled=True,
)


class RecordingTransport:
    """Stands in for Slack at the edge, so everything inside `deliver` stays real."""

    sends: list[tuple[str, AlertMessage]] = []
    provider = "slack"

    def channel_target(self, target: AlertDestinationData) -> str:
        return str(target.get("slack_channel_id", ""))

    def deliver(
        self, *, team_id: int, target: AlertDestinationData, message: AlertMessage, in_reply_to: Any = None
    ) -> MessageHandle | None:
        RecordingTransport.sends.append((self.channel_target(target), message))
        return MessageHandle(external_ref={"channel": self.channel_target(target), "ts": "1"})


class PagingTransport(RecordingTransport):
    provider = "pagerduty"

    def channel_target(self, target: AlertDestinationData) -> str:
        return str(target.get("pagerduty_routing_key", ""))


class RefusingTransport(RecordingTransport):
    provider = "webhook"

    def deliver(self, **kwargs: Any) -> MessageHandle | None:
        raise DeliveryError("The webhook destination refused the message with status 410.")


class HeldTransport(RecordingTransport):
    provider = "teams"

    def deliver(self, **kwargs: Any) -> MessageHandle | None:
        raise ThreadBusy("thread is being posted to by another send")


def _request(
    team_id: int,
    *,
    configuration_id: str = "cfg-1",
    sends_messages: bool = True,
    incident_actions: dict[str, IncidentAction] | None = None,
    owned_by_platform: bool = False,
    overflowed: int = 0,
    overflow_is_lower_bound: bool = False,
    parts: int = 1,
    part: int = 0,
) -> AlertDeliveryRequest:
    return AlertDeliveryRequest(
        source=SourceKind.LOGS,
        team_id=team_id,
        configuration_id=configuration_id,
        evaluation_key="eval-1",
        destination_alert_id="legacy-1",
        event_ids_by_kind={"firing": FIRING_EVENT, "resolved": RESOLVED_EVENT},
        sends_messages=sends_messages,
        incident_actions=incident_actions or {},
        event_ids_by_incident_action={"trigger": OPENED_EVENT, "resolve": CLOSED_EVENT},
        owned_by_platform=owned_by_platform,
        overflowed=overflowed,
        overflow_is_lower_bound=overflow_is_lower_bound,
        parts=parts,
        part=part,
    )


def _transition(
    kind: AlertEventKind, grouping_key: str = "", episode_started_at: datetime | None = FIRING
) -> AnnouncedTransition:
    return AnnouncedTransition(
        grouping_key=grouping_key,
        kind=kind,
        episode_started_at=episode_started_at,
        value=None,
        labels={},
        condition={},
        source_config={},
        error_message=None,
        occurred_at=FIRING,
    )


def _announcement(*transitions: AnnouncedTransition) -> EvaluationAnnouncement:
    return EvaluationAnnouncement(
        source=SourceKind.LOGS,
        configuration_id="cfg-1",
        alert_name="API errors",
        consecutive_failures=0,
        transitions=transitions,
    )


def _group(
    data: AlertDestinationData, fully_enabled: bool = True, hog_function_ids: tuple[UUID, ...] = ()
) -> AlertDestinationGroup:
    return AlertDestinationGroup(hog_function_ids=hog_function_ids, data=data, fully_enabled=fully_enabled)


class TestDeliverEvaluation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        RecordingTransport.sends = []

    def _run(
        self,
        announced: Any,
        by_event: dict[str, list[AlertDestinationGroup]],
        live: bool | Exception = True,
        transports: dict[DestinationType, type] | None = None,
        sends_messages: bool = True,
        incident_actions: dict[str, IncidentAction] | None = None,
        owned_by_platform: bool = False,
        overflowed: int = 0,
        overflow_is_lower_bound: bool = False,
        parts: int = 1,
        part: int = 0,
        kinds: dict[str, AlertEventKind] | None = None,
    ) -> Any:
        def groups(*, team_id: int, alert_id: str, allowed_event_ids: list[str]) -> list[AlertDestinationGroup]:
            return by_event.get(allowed_event_ids[0], [])

        with (
            patch(
                "products.alerts_platform.backend.delivery.team_flags.posthoganalytics.feature_enabled",
                **({"side_effect": live} if isinstance(live, Exception) else {"return_value": live}),
            ),
            patch(f"{_MODULE}.announcement", return_value=announced),
            patch(f"{_MODULE}.announced_kinds", return_value=kinds or {}),
            patch(f"{_MODULE}.list_alert_destination_groups", side_effect=groups),
            patch(f"{_MODULE}.DatabaseThreadStore"),
            # The path is covered by `TestDeliveryPath`. Without an emitter every alert delivers natively.
            patch.dict(delivery_paths._emitters, clear=True),
            patch.dict(
                f"{_MODULE}._TRANSPORTS",
                {
                    DestinationType.SLACK: RecordingTransport,
                    DestinationType.PAGERDUTY: PagingTransport,
                    **(transports or {}),
                },
            ),
        ):
            return deliver_evaluation(
                _request(
                    self.team.id,
                    sends_messages=sends_messages,
                    incident_actions=incident_actions,
                    owned_by_platform=owned_by_platform,
                    overflowed=overflowed,
                    overflow_is_lower_bound=overflow_is_lower_bound,
                    parts=parts,
                    part=part,
                )
            )

    def test_a_destination_hears_only_about_the_kinds_it_subscribed_to(self) -> None:
        # One group fires while another resolves. A destination that asked for firings must not
        # be told about the resolve just because the same evaluation produced it.
        announced = _announcement(
            _transition(AlertEventKind.FIRING, "checkout"),
            _transition(AlertEventKind.RESOLVED, "search"),
        )
        fires_only = cast(AlertDestinationData, {**SLACK, "slack_channel_id": "C-fires"})
        resolves_only = cast(AlertDestinationData, {**SLACK, "slack_channel_id": "C-resolves"})

        self._run(announced, {FIRING_EVENT: [_group(fires_only)], RESOLVED_EVENT: [_group(resolves_only)]})

        assert sorted((channel, m.headline) for channel, m in RecordingTransport.sends) == [
            ("C-fires", "Log alert 'API errors' is firing"),
            ("C-resolves", "Log alert 'API errors' is resolved"),
        ]

    def test_each_send_is_recorded_under_the_hog_function_of_the_event_it_sent(self) -> None:
        firing_function = UUID("00000000-0000-0000-0000-00000000000f")
        resolved_function = UUID("00000000-0000-0000-0000-00000000000a")
        announced = _announcement(
            _transition(AlertEventKind.FIRING, "checkout"),
            _transition(AlertEventKind.RESOLVED, "search"),
        )

        with patch("products.alerts_platform.backend.delivery.dispatch.record_delivery") as recorded:
            self._run(
                announced,
                {
                    FIRING_EVENT: [_group(SLACK, hog_function_ids=(firing_function,))],
                    RESOLVED_EVENT: [_group(SLACK, hog_function_ids=(resolved_function,))],
                },
            )

        assert sorted(c.kwargs["destination_id"] for c in recorded.call_args_list) == sorted(
            [str(firing_function), str(resolved_function)]
        )

    @parameterized.expand(
        [
            ("exact", False, "3 more groups not tracked because this alert is at its group limit"),
            ("lower_bound", True, "At least 3 more groups not tracked because this alert is at its group limit"),
        ]
    )
    def test_a_destination_subscribed_to_both_hears_about_both(
        self, _name: str, overflow_is_lower_bound: bool, notice: str
    ) -> None:
        announced = _announcement(
            _transition(AlertEventKind.FIRING, "checkout"),
            _transition(AlertEventKind.RESOLVED, "search"),
        )

        self._run(
            announced,
            {FIRING_EVENT: [_group(SLACK)], RESOLVED_EVENT: [_group(SLACK)]},
            overflowed=3,
            overflow_is_lower_bound=overflow_is_lower_bound,
        )

        assert sorted(m.headline for _, m in RecordingTransport.sends) == [
            "Log alert 'API errors' is firing",
            "Log alert 'API errors' is resolved",
        ]
        overflow_notices = [
            detail.value
            for _, m in RecordingTransport.sends
            for detail in m.details
            if detail.label == "Untracked groups"
        ]
        assert overflow_notices == [notice]

    def test_each_destination_hears_the_overflow_once_across_the_parts_of_a_split_delivery(self) -> None:
        # Sorted by key, the firing lands in part 0 and the resolve in part 1, so a destination
        # that asked only for resolves sends nothing from part 0.
        by_part = [_transition(AlertEventKind.FIRING, "checkout"), _transition(AlertEventKind.RESOLVED, "search")]
        fires_only = cast(AlertDestinationData, {**SLACK, "slack_channel_id": "C-fires"})
        resolves_only = cast(AlertDestinationData, {**SLACK, "slack_channel_id": "C-resolves"})

        notices: list[str] = []
        for part in range(2):
            RecordingTransport.sends = []
            self._run(
                _announcement(by_part[part]),
                {
                    FIRING_EVENT: [_group(fires_only), _group(SLACK)],
                    RESOLVED_EVENT: [_group(resolves_only), _group(SLACK)],
                },
                overflowed=3,
                parts=2,
                part=part,
                kinds={transition.grouping_key: transition.kind for transition in by_part},
            )
            notices += [
                channel
                for channel, m in RecordingTransport.sends
                for detail in m.details
                if detail.label == "Untracked groups"
            ]

        assert sorted(notices) == ["C-1", "C-fires", "C-resolves"]

    def test_a_delivery_that_exists_only_for_its_incident_sends_no_message(self) -> None:
        # Even a kind its destinations subscribe to reaches none of them when the source announced nothing.
        outcome = self._run(
            _announcement(_transition(AlertEventKind.RESOLVED)),
            {RESOLVED_EVENT: [_group(SLACK)]},
            sends_messages=False,
        )

        assert RecordingTransport.sends == []
        assert outcome.sent == 0

    @parameterized.expand(
        [
            # Cooldown held the resolve, so chat hears nothing and the incident still closes.
            ("a_held_resolve", AlertEventKind.CHECK, False, IncidentAction.RESOLVE, []),
            (
                "an_announced_fire",
                AlertEventKind.FIRING,
                True,
                IncidentAction.TRIGGER,
                ["Log alert 'API errors' is firing"],
            ),
        ]
    )
    def test_an_incident_action_reaches_only_the_incident_subscription(
        self,
        _name: str,
        kind: AlertEventKind,
        sends_messages: bool,
        action: IncidentAction,
        chat_headlines: list[str],
    ) -> None:
        self._run(
            _announcement(_transition(kind)),
            {
                FIRING_EVENT: [_group(SLACK)],
                RESOLVED_EVENT: [_group(SLACK)],
                OPENED_EVENT: [_group(PAGERDUTY)],
                CLOSED_EVENT: [_group(PAGERDUTY)],
            },
            sends_messages=sends_messages,
            incident_actions={"": action},
        )

        assert [m.headline for channel, m in RecordingTransport.sends if channel == "C-1"] == chat_headlines
        assert [m.incident_action for channel, m in RecordingTransport.sends if channel == "R-1"] == [action]

    @parameterized.expand([("owned_by_the_platform", True, "posthog-alert-legacy-1"), ("live_delivery", False, None)])
    def test_only_an_alert_the_platform_owns_resolves_under_its_source_incident_key(
        self, _name: str, owned_by_platform: bool, expected: str | None
    ) -> None:
        self._run(
            _announcement(_transition(AlertEventKind.RESOLVED)),
            {CLOSED_EVENT: [_group(PAGERDUTY)]},
            incident_actions={"": IncidentAction.RESOLVE},
            owned_by_platform=owned_by_platform,
        )

        assert [m.source_incident_key for channel, m in RecordingTransport.sends if channel == "R-1"] == [expected]

    def test_a_destination_with_no_transport_is_skipped_rather_than_failing_the_send(self) -> None:
        outcome = self._run(
            _announcement(_transition(AlertEventKind.FIRING)),
            {FIRING_EVENT: [_group(SLACK), _group(UNSUPPORTED)]},
        )

        assert [channel for channel, _ in RecordingTransport.sends] == ["C-1"]
        assert (outcome.sent, outcome.skipped_without_transport) == (1, 1)

    @parameterized.expand(
        [
            ("a_refusal_is_raised_after_the_rest_are_sent", DeliveryError, [WEBHOOK, SLACK]),
            ("a_held_thread_wins_over_a_refusal", ThreadBusy, [WEBHOOK, TEAMS, SLACK]),
        ]
    )
    def test_one_destination_failing_does_not_cost_the_others_their_message(
        self, _name: str, raised: type[Exception], destinations: list[AlertDestinationData]
    ) -> None:
        with pytest.raises(raised, match="status 410"):
            self._run(
                _announcement(_transition(AlertEventKind.FIRING)),
                {FIRING_EVENT: [_group(destination) for destination in destinations]},
                transports={DestinationType.WEBHOOK: RefusingTransport, DestinationType.TEAMS: HeldTransport},
            )

        assert [channel for channel, _ in RecordingTransport.sends] == ["C-1"]

    def test_a_destination_that_is_not_fully_enabled_receives_nothing(self) -> None:
        outcome = self._run(
            _announcement(_transition(AlertEventKind.FIRING)),
            {FIRING_EVENT: [_group(SLACK, fully_enabled=False)]},
        )

        assert RecordingTransport.sends == []
        assert outcome.sent == 0

    def test_every_message_links_to_the_alert_page_the_request_names_and_to_its_project(self) -> None:
        url = "https://app.example.com/project/7/logs/alerts/legacy-1"

        with (
            patch(
                "products.alerts_platform.backend.delivery.team_flags.posthoganalytics.feature_enabled",
                return_value=True,
            ),
            patch(f"{_MODULE}.announcement", return_value=_announcement(_transition(AlertEventKind.FIRING))),
            patch(f"{_MODULE}.list_alert_destination_groups", return_value=[_group(SLACK)]),
            patch(f"{_MODULE}.DatabaseThreadStore"),
            patch.dict(f"{_MODULE}._TRANSPORTS", {DestinationType.SLACK: RecordingTransport}),
        ):
            deliver_evaluation(replace(_request(self.team.id), source_alert_url=url))

        assert [(m.alert_url, m.project) for _, m in RecordingTransport.sends] == [
            (url, MessageLink(label=self.team.name, url=absolute_uri(f"/project/{self.team.id}")))
        ]

    def test_an_evaluation_that_announced_nothing_sends_nothing(self) -> None:
        outcome = self._run(None, {FIRING_EVENT: [_group(SLACK)]})

        assert RecordingTransport.sends == []
        assert outcome.sent == 0

    def test_a_team_without_the_flag_is_not_contacted(self) -> None:
        outcome = self._run(
            _announcement(_transition(AlertEventKind.FIRING)), {FIRING_EVENT: [_group(SLACK)]}, live=False
        )

        assert RecordingTransport.sends == []
        assert outcome.live is False

    def test_the_flag_is_read_against_the_project(self) -> None:
        # Without the project group the condition never matches, and the platform stays silent
        # with nothing to say why.
        with (
            patch(
                "products.alerts_platform.backend.delivery.team_flags.posthoganalytics.feature_enabled",
                return_value=False,
            ) as flag,
            patch(f"{_MODULE}.announcement", return_value=None),
        ):
            deliver_evaluation(_request(self.team.id))

        assert flag.call_args.args[0] == LIVE_DELIVERY_FLAG
        assert flag.call_args.kwargs["groups"]["project"] == str(self.team.id)
        assert flag.call_args.kwargs["group_properties"]["project"]["uuid"] == str(self.team.uuid)

    @parameterized.expand([("owned_by_the_source", False), ("owned_by_the_platform", True)])
    def test_a_flag_that_cannot_be_read_silences_only_alerts_the_source_still_delivers(
        self, _name: str, delivers: bool
    ) -> None:
        outcome = self._run(
            _announcement(_transition(AlertEventKind.FIRING)),
            {FIRING_EVENT: [_group(SLACK)]},
            live=RuntimeError("flags unreachable"),
            owned_by_platform=delivers,
        )

        assert (outcome.live, len(RecordingTransport.sends)) == (delivers, int(delivers))

    @parameterized.expand(
        [
            ("keeps_the_legacy_body", True, "1", "legacy"),
            ("moved_to_alertmanager", False, "2", "4"),
            ("flag_unreadable", RuntimeError("flags unreachable"), None, None),
            # The SDK swallows a failed lookup and answers None.
            ("flag_lookup_swallowed", None, None, None),
        ]
    )
    def test_a_webhook_gets_the_body_its_team_still_receives(
        self, _name: str, keeps_legacy: bool | Exception | None, header: str | None, body_version: str | None
    ) -> None:
        flag_reads: list[str] = []

        def flag(key: str, *_args: Any, **_kwargs: Any) -> bool | None:
            flag_reads.append(key)
            if key == LIVE_DELIVERY_FLAG:
                return True
            if isinstance(keeps_legacy, Exception):
                raise keeps_legacy
            return keeps_legacy

        def legacy_body(**kwargs: Any) -> dict[str, Any]:
            return {"version": "legacy", "alert_id": kwargs["alert_id"]}

        with (
            patch(
                "products.alerts_platform.backend.delivery.team_flags.posthoganalytics.feature_enabled",
                side_effect=flag,
            ),
            patch(f"{_MODULE}.announcement", return_value=_announcement(_transition(AlertEventKind.FIRING))),
            patch(f"{_MODULE}.list_alert_destination_groups", return_value=[_group(WEBHOOK), _group(SECOND_WEBHOOK)]),
            patch(f"{_MODULE}.DatabaseThreadStore"),
            patch.dict(f"{_LEGACY_MODULE}._bodies", {SourceKind.LOGS: legacy_body}),
            patch(f"{_WEBHOOK_URL_MODULE}.post_json") as post,
            patch(f"{_MODULE}.record_delivery") as recorded,
        ):
            if header is None:
                with pytest.raises(DeliveryError):
                    deliver_evaluation(_request(self.team.id))
                post.assert_not_called()
                # Each blocked webhook still counts as a failed delivery.
                assert [c.kwargs["succeeded"] for c in recorded.call_args_list] == [False, False]
                # One failed lookup per evaluation, however many webhooks it has.
                assert flag_reads.count(LEGACY_WEBHOOK_BODY_FLAG) == 1
                return
            deliver_evaluation(_request(self.team.id))

        assert post.call_args.kwargs["headers"] == {"X-PostHog-Webhook-Version": header}
        assert post.call_args.args[1]["version"] == body_version

    @parameterized.expand([("registered_a_body", True, True), ("registered_none", False, False)])
    def test_native_delivery_keeps_the_webhook_body_only_for_a_source_that_registered_one(
        self, _name: str, registered: bool, keeps: bool
    ) -> None:
        bodies: dict[SourceKind, Any] = {SourceKind.INSIGHT: lambda **_kwargs: {}} if registered else {}
        with (
            patch.dict(f"{_LEGACY_MODULE}._bodies", bodies, clear=True),
            patch(
                "products.alerts_platform.backend.delivery.team_flags.posthoganalytics.feature_enabled",
                return_value=True,
            ),
        ):
            assert legacy_webhook.native_sends_legacy_body(SourceKind.INSIGHT, self.team) is keeps

    def test_logs_registers_its_legacy_webhook_body_at_startup(self) -> None:
        # Every other case here patches the registry, so none of them notices a missing registration,
        # which would send grandfathered teams the Alertmanager body without any error.
        assert legacy_webhook.body_for(SourceKind.LOGS) is not None
        assert delivery_paths.emitter_for(SourceKind.LOGS) is not None

    def test_the_destination_owner_registers_its_lookup_at_startup(self) -> None:
        # Every other case here patches the lookup, so none of them notices a missing registration.
        assert delivery_paths._chooser is not None
        # Without it an insight alert on the HogFunction path sends nothing at all.
        assert delivery_paths.emitter_for(SourceKind.INSIGHT) is not None
        # Without it a native insight message carries only the platform's "Value" line.
        assert SourceKind.INSIGHT in describers._describers
        assert (
            list_alert_destination_groups(team_id=self.team.id, alert_id="unknown", allowed_event_ids=[FIRING_EVENT])
            == []
        )


class TestDeliveryPath(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        RecordingTransport.sends = []
        self.emitted: list[tuple[LegacyEventEmission, ...]] = []
        self.configuration = PlatformAlertConfiguration.objects.for_team(self.team.id).create(
            team=self.team, name="API errors", source_kind=SourceKind.LOGS, check_interval_minutes=1
        )

    def _emit(self, *, emissions: tuple[LegacyEventEmission, ...], **_kwargs: Any) -> None:
        self.emitted.append(tuple(emissions))

    def _run(
        self,
        announced: EvaluationAnnouncement,
        chooser: Any,
        *,
        owned_by_platform: bool = True,
        incident_actions: dict[str, IncidentAction] | None = None,
        emitter: Any = None,
        groups: list[AlertDestinationGroup] | None = None,
        transport: type = RecordingTransport,
        real_thread_store: bool = False,
    ) -> Any:
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "products.alerts_platform.backend.delivery.team_flags.posthoganalytics.feature_enabled",
                    return_value=True,
                )
            )
            stack.enter_context(patch(f"{_MODULE}.announcement", return_value=announced))
            stack.enter_context(
                patch(f"{_MODULE}.list_alert_destination_groups", return_value=groups or [HOG_FUNCTION_SLACK])
            )
            if not real_thread_store:
                stack.enter_context(patch(f"{_MODULE}.DatabaseThreadStore"))
            stack.enter_context(patch.dict(f"{_MODULE}._TRANSPORTS", {DestinationType.SLACK: transport}))
            stack.enter_context(patch.dict(delivery_paths._emitters, {SourceKind.LOGS: emitter or self._emit}))
            stack.enter_context(patch.object(delivery_paths, "_chooser", chooser))
            return deliver_evaluation(
                _request(
                    self.team.id,
                    configuration_id=str(self.configuration.id),
                    owned_by_platform=owned_by_platform,
                    incident_actions=incident_actions,
                )
            )

    @staticmethod
    def _chooses(path: DeliveryPath) -> Any:
        return lambda **_kwargs: path

    @staticmethod
    def _fails(**_kwargs: Any) -> DeliveryPath:
        raise RuntimeError("classifier down")

    # The subscriber group stands in for email and in-app, which are no HogFunction and never see an emitted event.
    @parameterized.expand(
        [
            ("stock_destinations_send_natively", True, DeliveryPath.NATIVE, 0, ["C-1", "C-2"]),
            ("customized_destinations_emit_for_their_hog_functions", True, DeliveryPath.HOG_FUNCTION, 1, ["C-2"]),
            # The source's own stack still emits these events, so emitting them here would send twice.
            ("an_alert_the_source_owns_never_emits", False, DeliveryPath.HOG_FUNCTION, 0, ["C-1", "C-2"]),
            ("a_chooser_that_fails_emits", True, None, 1, ["C-2"]),
        ]
    )
    def test_an_alert_delivers_through_the_path_its_destinations_allow(
        self, _name: str, owned_by_platform: bool, path: DeliveryPath | None, emitted: int, native_channels: list[str]
    ) -> None:
        chooser = self._chooses(path) if path else self._fails
        outcome = self._run(
            _announcement(_transition(AlertEventKind.FIRING)),
            chooser,
            owned_by_platform=owned_by_platform,
            groups=[HOG_FUNCTION_SLACK, SUBSCRIBER],
        )

        assert len(self.emitted) == emitted
        assert sorted(channel for channel, _ in RecordingTransport.sends) == native_channels
        assert (outcome.emitted_transitions, outcome.emitted_events) == (emitted, emitted)

    def test_a_firing_and_its_resolve_take_the_path_the_firing_took(self) -> None:
        fired = self._run(
            _announcement(_transition(AlertEventKind.FIRING)),
            self._chooses(DeliveryPath.HOG_FUNCTION),
            incident_actions={"": IncidentAction.TRIGGER},
        )
        # One transition, emitted as its message event and its incident event.
        assert (fired.emitted_transitions, fired.emitted_events) == (1, 2)
        # Every destination became stock mid-firing. The resolve still closes what the HogFunction opened.
        self._run(
            _announcement(_transition(AlertEventKind.RESOLVED)),
            self._chooses(DeliveryPath.NATIVE),
            incident_actions={"": IncidentAction.RESOLVE},
        )
        # The next firing reads the destinations again.
        self._run(
            _announcement(_transition(AlertEventKind.FIRING, episode_started_at=datetime(2026, 9, 30, 10, tzinfo=UTC))),
            self._chooses(DeliveryPath.NATIVE),
        )

        assert [
            [(e.transition.kind, e.sends_message, e.incident_action) for e in emissions] for emissions in self.emitted
        ] == [
            [(AlertEventKind.FIRING, True, IncidentAction.TRIGGER)],
            [(AlertEventKind.RESOLVED, True, IncidentAction.RESOLVE)],
        ]
        assert len(RecordingTransport.sends) == 1

    def test_an_emission_the_broker_did_not_take_fails_the_delivery_so_it_retries(self) -> None:
        def refuse(**_kwargs: Any) -> None:
            raise RuntimeError("not acknowledged")

        with pytest.raises(DeliveryError):
            self._run(
                _announcement(_transition(AlertEventKind.FIRING, episode_started_at=None)),
                self._chooses(DeliveryPath.HOG_FUNCTION),
                emitter=refuse,
            )

    def test_a_rerun_after_a_refused_subscriber_send_emits_once(self) -> None:
        with recorded_metrics() as metrics:
            for _ in range(2):
                with pytest.raises(DeliveryError):
                    self._run(
                        _announcement(_transition(AlertEventKind.FIRING)),
                        self._chooses(DeliveryPath.HOG_FUNCTION),
                        groups=[HOG_FUNCTION_SLACK, SUBSCRIBER],
                        transport=RefusingTransport,
                        real_thread_store=True,
                    )

        assert len(self.emitted) == 1
        assert [
            (m.attributes["outcome"], m.value)
            for m in metrics
            if m.name == "alerts_platform_deliveries_total" and m.attributes["path"] == "hog_function"
        ] == [("sent", 1), ("already_delivered", 1)]

    def test_a_held_subscriber_thread_holds_the_emission_for_the_rerun(self) -> None:
        with pytest.raises(ThreadBusy):
            self._run(
                _announcement(_transition(AlertEventKind.FIRING)),
                self._chooses(DeliveryPath.HOG_FUNCTION),
                groups=[HOG_FUNCTION_SLACK, SUBSCRIBER],
                transport=HeldTransport,
            )

        assert self.emitted == []
