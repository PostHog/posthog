"""The workflow that would replace a customized alert destination's HogFunctions.

One destination is one group of HogFunctions, one per event kind, as the alert page lists it. Its
workflow subscribes to `$alert_transition` for the alert's platform configuration, branches on the
transition, and runs one function step per HogFunction with the same template and inputs.

A source copies its legacy event properties into the event's `source` block, so a placeholder such
as `{event.properties.result_count}` becomes `{event.properties.source.result_count}`. A placeholder
whose value differs in a workflow, and anything else a step cannot carry, stops the port and is
reported for a person to read.
"""

from __future__ import annotations

import re
import base64
import binascii
from collections import Counter
from collections.abc import Collection, Iterable, Iterator, Mapping
from dataclasses import field
from typing import Any, Final, Literal
from uuid import UUID

from django.db import transaction

from posthog.dataclasses import frozen

from products.alerts.backend.facade.contracts import (
    DestinationBucket,
    DestinationEligibility,
    DestinationHoldBack,
    FlowDrafts,
    FlowPort,
    FlowPortIssue,
    FlowPortProblem,
    NamedAlert,
)
from products.alerts.backend.logic.destination_configs import SPEC_BY_TEMPLATE_ID, input_value
from products.alerts.backend.logic.destination_eligibility import (
    RECEIVES_ALERT_EVENTS,
    bound_to_one_alert,
    bucket_for,
    classify_destinations_by_alert,
    most_restrictive,
    named_alert_ids,
)
from products.alerts.backend.logic.destinations import (
    AlertDestinationRow,
    group_alert_destination_rows,
    owned_alert_destinations_qs,
    stored_inputs,
)
from products.alerts_platform.backend.facade.api import configuration_ids_by_legacy_id, workflow_trigger_refusal
from products.alerts_platform.backend.facade.contracts import ALERT_TRANSITION_EVENT, AlertEventKind
from products.cdp.backend.models.hog_functions.hog_function import DERIVED_FILTER_KEYS, HogFunction
from products.workflows.backend.facade.contracts import DraftWorkflowRefused
from products.workflows.backend.facade.enums import HogFlowOriginProduct
from products.workflows.backend.facade.workflows import workflows_for_origin
from products.workflows.backend.facade.writes import create_draft_workflow

# Native delivery sends these, so they need no workflow.
_NATIVE_BUCKETS: Final = frozenset(
    {DestinationBucket.STOCK, DestinationBucket.STATIC_HEADERS, DestinationBucket.TEMPLATED_HEADERS}
)

_STOPPING_HOLD_BACKS: Final = {
    DestinationHoldBack.CODE: FlowPortProblem.EDITED_CODE,
    DestinationHoldBack.NO_TEMPLATE: FlowPortProblem.NO_TEMPLATE,
    DestinationHoldBack.CUSTOM_INPUTS: FlowPortProblem.CUSTOM_INPUTS,
    DestinationHoldBack.MAPPINGS: FlowPortProblem.MAPPINGS,
    DestinationHoldBack.REFUSED_ADDRESS: FlowPortProblem.REFUSED_ADDRESS,
}

# The workflow write path compiles these again from the copied values.
_DERIVED_INPUT_KEYS: Final = frozenset({"bytecode", "bytecode_error", "bytecode_contract", "transpiled"})
_KNOWN_FILTER_KEYS: Final = frozenset({"source", "events", "properties", "filter_test_accounts", *DERIVED_FILTER_KEYS})

# The rule a workflow webhook step applies before it signs (`resolveStandardWebhooksKey` in Node).
_SIGNING_SECRET_PREFIX: Final = "whsec_"
_SIGNING_SECRET_PATTERN: Final = re.compile(r"[A-Za-z0-9+/]+={0,2}")
_MIN_SIGNING_SECRET_BYTES: Final = 24

# A reference to a global inside a template, such as `event.properties.result_count` or
# `person['email']`. The lookbehind skips a key named like a global, such as `inputs.event`.
_REFERENCE: Final = re.compile(
    r"(?<![\w.$])(event|person|groups|source|project|inputs)(?![\w$])((?:\.[A-Za-z_$][\w$]*|\[[^\[\]]*\])*)"
)
_LIQUID_CLOSERS: Final = {"{{": "}}", "{%": "%}"}
_BRACKET: Final = re.compile(r"\[([^\[\]]*)\]")
_QUOTED: Final = re.compile(r"'[^']*'|\"[^\"]*\"")
# The event's own fields keep their meaning: the transition's id and time.
_KEPT_EVENT_FIELDS: Final = frozenset({".uuid", ".timestamp"})

_ACTION_IDS: Final = {"trigger": "trigger_node", "branch": "branch_transition", "exit": "exit_node"}


@frozen
class _Span:
    start: int
    stop: int


@frozen
class _Segment:
    """A run of a template expression: code, a string literal, or an f-string, whose `{...}` parts are code."""

    start: int
    stop: int
    kind: Literal["code", "string", "fstring"]


@frozen(frozen=False)
class PlaceholderLog:
    """What `rewrite_template` changed and what it could not, across every template of one function."""

    rewritten: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)


def _valid_signing_secret(secret: Any) -> bool:
    if not isinstance(secret, str):
        return False
    encoded = secret.removeprefix(_SIGNING_SECRET_PREFIX)
    if not _SIGNING_SECRET_PATTERN.fullmatch(encoded):
        return False
    # Node decodes an unpadded secret too, so the padding is restored before Python decodes it.
    try:
        key = base64.b64decode(encoded + "=" * (-len(encoded) % 4))
    except (binascii.Error, ValueError):
        return False
    return len(key) >= _MIN_SIGNING_SECRET_BYTES


def _segments(text: str, start: int, stop: int) -> list[_Segment]:
    """`text[start:stop]` split into code and string literals. A string literal can hold a brace or a
    reference that is only text."""
    segments: list[_Segment] = []
    index = start
    while index < stop:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char in "'\"":
            fstring = index > start and text[index - 1] in "fF"
            segments.append(_Segment(start=start, stop=index, kind="code"))
            opened = index
            index += 1
            while index < stop and text[index] != char:
                index += 2 if text[index] == "\\" else 1
            segments.append(_Segment(start=opened, stop=index + 1, kind="fstring" if fstring else "string"))
            start = index + 1
        index += 1
    segments.append(_Segment(start=start, stop=stop, kind="code"))
    return [segment for segment in segments if segment.stop > segment.start]


def _liquid_tags(text: str) -> list[_Span]:
    # Linear on purpose: a lazy regex rescans the rest of the text for every unclosed `{{`.
    tags: list[_Span] = []
    next_open = {opener: text.find(opener) for opener in _LIQUID_CLOSERS}
    index = 0
    while True:
        for opener, position in next_open.items():
            if position != -1 and position < index:
                next_open[opener] = text.find(opener, index)
        found = [(position, opener) for opener, position in next_open.items() if position != -1]
        if not found:
            return tags
        start, opener = min(found)
        stop = text.find(_LIQUID_CLOSERS[opener], start + 2)
        if stop == -1:
            # No later opener of this kind can close either, but the other kind still can.
            next_open[opener] = -1
            continue
        tags.append(_Span(start=start, stop=stop + 2))
        index = stop + 2


def _hog_expressions(text: str) -> list[_Span]:
    # A Hog template is literal text with `{expression}` parts, where `\{` is a literal brace and an
    # expression may hold braces of its own, such as a dict or a brace inside a string literal.
    expressions: list[_Span] = []
    depth = 0
    start = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if depth and char in "'\"":
            index += 1
            while index < len(text) and text[index] != char:
                index += 2 if text[index] == "\\" else 1
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0:
                expressions.append(_Span(start=start, stop=index + 1))
        index += 1
    return expressions


def _kept(root: str, path: str) -> bool:
    return root in ("inputs", "project") or (root == "event" and path in _KEPT_EVENT_FIELDS)


def _rewrite_reference(match: re.Match[str], log: PlaceholderLog) -> str:
    root, path = match.group(1), match.group(2)
    reference = match.group(0)
    # A computed key such as `inputs[event.properties.name]` reads a global the rewrite would miss.
    if any(_REFERENCE.search(_QUOTED.sub("", key)) for key in _BRACKET.findall(path)):
        log.unknown.append(reference)
        return reference
    if _kept(root, path):
        return reference
    if root == "event" and (path == ".properties" or path.startswith((".properties.", ".properties["))):
        new = f"event.properties.source{path.removeprefix('.properties')}"
        log.rewritten.append(f"{reference} -> {new}")
        return new
    log.unknown.append(reference)
    return reference


def _log_text_references(text: str, log: PlaceholderLog, *, bare: bool) -> None:
    # Text is not rewritten, but it may still be read at runtime, so a person checks it. A bare global such
    # as `event` is ordinary prose in literal text, and code inside an f-string.
    log.unknown.extend(
        match.group(0)
        for match in _REFERENCE.finditer(text)
        if (bare or match.group(2)) and not _kept(match.group(1), match.group(2))
    )


def rewrite_template(text: str, templating: Any, log: PlaceholderLog) -> str:
    """The template with its legacy event properties read from `source`. Only the template's code
    changes. A reference in literal text or in a string literal, such as one inside an f-string, may
    still be read at runtime, so it is logged as unknown for a person to check."""
    expressions = _liquid_tags(text) if templating == "liquid" else _hog_expressions(text)
    parts: list[str] = []
    end = 0
    for expression in [*expressions, _Span(start=len(text), stop=len(text))]:
        literal = text[end : expression.start]
        _log_text_references(literal, log, bare=False)
        parts.append(literal)
        for segment in _segments(text, expression.start, expression.stop):
            piece = text[segment.start : segment.stop]
            if segment.kind == "code":
                piece = _REFERENCE.sub(lambda match: _rewrite_reference(match, log), piece)
            else:
                _log_text_references(piece, log, bare=segment.kind == "fstring")
            parts.append(piece)
        end = expression.stop
    return "".join(parts)


def _rewrite_value(value: Any, templating: Any, log: PlaceholderLog) -> Any:
    if isinstance(value, str):
        return rewrite_template(value, templating, log)
    if isinstance(value, dict):
        # The template renderer keeps dict keys as written, so only values are templates.
        return {key: _rewrite_value(item, templating, log) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite_value(item, templating, log) for item in value]
    return value


def _unknown_placeholders(log: PlaceholderLog, hog_function_id: UUID | None) -> list[FlowPortIssue]:
    return [
        FlowPortIssue(problem=FlowPortProblem.UNKNOWN_PLACEHOLDER, hog_function_id=hog_function_id, detail=reference)
        for reference in log.unknown
    ]


def _filter_issues(function: HogFunction) -> list[FlowPortIssue]:
    filters = function.filters if isinstance(function.filters, dict) else {}
    extra = sorted(set(filters) - _KNOWN_FILTER_KEYS)
    if filters.get("filter_test_accounts"):
        extra.append("filter_test_accounts")
    properties = [prop for prop in filters.get("properties") or () if isinstance(prop, dict)]
    extra.extend(str(prop.get("key")) for prop in properties if prop.get("key") != "alert_id")
    if any(isinstance(event, dict) and event.get("properties") for event in filters.get("events") or ()):
        extra.append("events.properties")
    issues = [
        FlowPortIssue(problem=FlowPortProblem.EXTRA_FILTERS, hog_function_id=function.id, detail=key) for key in extra
    ]
    if not bound_to_one_alert(filters) or len(named_alert_ids(filters)) != 1:
        issues.append(FlowPortIssue(problem=FlowPortProblem.UNBOUND, hog_function_id=function.id))
    return issues


def _transition(
    function: HogFunction, transition_by_event_id: Mapping[str, AlertEventKind]
) -> AlertEventKind | FlowPortIssue:
    filters = function.filters if isinstance(function.filters, dict) else {}
    event_ids = [str(event.get("id")) for event in filters.get("events") or () if isinstance(event, dict)]
    if len(event_ids) != 1:
        return FlowPortIssue(problem=FlowPortProblem.EXTRA_FILTERS, hog_function_id=function.id, detail="events")
    transition = transition_by_event_id.get(event_ids[0])
    if transition is None:
        return FlowPortIssue(
            problem=FlowPortProblem.EVENT_WITHOUT_TRANSITION, hog_function_id=function.id, detail=event_ids[0]
        )
    return transition


def _ported_inputs(function: HogFunction, log: PlaceholderLog) -> dict[str, Any]:
    """The function's inputs, secret ones included, with their placeholders rewritten for a workflow.

    The workflow write path moves secret inputs back into encrypted storage by the template's schema.
    """
    ported: dict[str, Any] = {}
    for key, entry in stored_inputs(function.inputs, function.encrypted_inputs).items():
        if not isinstance(entry, dict):
            continue
        kept = {name: value for name, value in entry.items() if name not in _DERIVED_INPUT_KEYS}
        if "value" in kept:
            kept["value"] = _rewrite_value(kept["value"], kept.get("templating"), log)
        ported[key] = kept
    return ported


def _ported_masking(functions: list[HogFunction], log: PlaceholderLog) -> dict[str, Any] | FlowPortIssue | None:
    maskings = [
        {key: value for key, value in function.masking.items() if key not in _DERIVED_INPUT_KEYS}
        if isinstance(function.masking, dict)
        else None
        for function in functions
    ]
    if any(masking != maskings[0] for masking in maskings):
        return FlowPortIssue(problem=FlowPortProblem.MIXED_MASKING, hog_function_id=None)
    masking = maskings[0]
    if masking is None:
        return None
    # Each legacy function kept its own masking cache, and a workflow has one for every transition, so a
    # resolve would match the firing before it. No hash change fixes that and keeps an empty hash unmasked.
    if len(functions) > 1:
        return FlowPortIssue(problem=FlowPortProblem.MIXED_MASKING, hog_function_id=None, detail="transitions")
    return {**masking, "hash": _rewrite_value(masking.get("hash"), None, log)}


def _send_step_id(transition: str) -> str:
    return f"send_{transition}"


def _action(action_id: str, name: str, action_type: str, config: dict[str, Any]) -> dict[str, Any]:
    return {"id": action_id, "name": name, "description": "", "type": action_type, "config": config}


def _exact(key: str, value: list[str]) -> dict[str, Any]:
    return {"key": key, "value": value, "operator": "exact", "type": "event"}


def _flow(
    *,
    alert_name: str,
    configuration_id: UUID,
    template_id: str,
    steps: list[tuple[str, dict[str, Any]]],
    masking: dict[str, Any] | None,
) -> dict[str, Any]:
    spec = SPEC_BY_TEMPLATE_ID.get(template_id)
    label = spec.type.value if spec is not None else template_id
    transitions = [transition for transition, _ in steps]
    trigger = {
        "type": "internal-event",
        "filters": {
            "source": "internal-events",
            "events": [{"id": ALERT_TRANSITION_EVENT, "type": "events"}],
            "properties": [
                _exact("alert_configuration_id", [str(configuration_id)]),
                _exact("transition", transitions),
            ],
        },
    }
    trigger_id, branch_id, exit_id = _ACTION_IDS["trigger"], _ACTION_IDS["branch"], _ACTION_IDS["exit"]
    conditions = [
        {"name": transition, "filters": {"properties": [_exact("transition", [transition])]}}
        for transition in transitions
    ]
    send_steps = [
        _action(
            _send_step_id(transition),
            f"Send on {transition}",
            "function",
            {"template_id": template_id, "inputs": inputs},
        )
        for transition, inputs in steps
    ]
    edges = [
        {"from": trigger_id, "to": branch_id, "type": "continue"},
        *(
            {"from": branch_id, "to": step["id"], "type": "branch", "index": index}
            for index, step in enumerate(send_steps)
        ),
        {"from": branch_id, "to": exit_id, "type": "continue"},
        *({"from": step["id"], "to": exit_id, "type": "continue"} for step in send_steps),
    ]
    return {
        "name": f"{alert_name}: {label}",
        "status": "draft",
        "trigger": trigger,
        "trigger_masking": masking,
        "actions": [
            _action(trigger_id, "Alert transition", "trigger", trigger),
            _action(branch_id, "Which transition", "conditional_branch", {"conditions": conditions}),
            *send_steps,
            _action(exit_id, "Exit", "exit", {"reason": "Default exit"}),
        ],
        "edges": edges,
    }


def _port(
    *,
    alert_id: str,
    alert_name: str,
    configuration_id: UUID | None,
    group: list[HogFunction],
    eligibilities: Mapping[UUID, DestinationEligibility],
    bucket: DestinationBucket,
    transition_by_event_id: Mapping[str, AlertEventKind],
) -> FlowPort:
    issues: list[FlowPortIssue] = []
    if configuration_id is None:
        issues.append(FlowPortIssue(problem=FlowPortProblem.NO_PLATFORM_CONFIGURATION, hog_function_id=None))
    enabled = [function for function in group if function.enabled]
    if not enabled:
        issues.append(FlowPortIssue(problem=FlowPortProblem.NOTHING_ENABLED, hog_function_id=None))

    rewritten: list[str] = []
    steps: list[tuple[str, dict[str, Any]]] = []
    secret_input_keys: dict[str, tuple[str, ...]] = {}
    for function in enabled:
        issues.extend(
            FlowPortIssue(problem=_STOPPING_HOLD_BACKS[hold_back], hog_function_id=function.id)
            for hold_back in eligibilities[function.id].hold_backs
            if hold_back in _STOPPING_HOLD_BACKS
        )
        issues.extend(_filter_issues(function))
        secret = input_value(function.encrypted_inputs or {}, "signing_secret")
        if secret and not _valid_signing_secret(secret):
            issues.append(FlowPortIssue(problem=FlowPortProblem.INVALID_SIGNING_SECRET, hog_function_id=function.id))
        log = PlaceholderLog()
        inputs = _ported_inputs(function, log)
        rewritten.extend(log.rewritten)
        issues.extend(_unknown_placeholders(log, function.id))
        transition = _transition(function, transition_by_event_id)
        if isinstance(transition, FlowPortIssue):
            issues.append(transition)
        else:
            steps.append((str(transition), inputs))
            # A secret schema key with no value is stored as `None`, and the step carries nothing for it.
            secret_input_keys[_send_step_id(str(transition))] = tuple(
                sorted(key for key, entry in (function.encrypted_inputs or {}).items() if isinstance(entry, dict))
            )

    shared = Counter(transition for transition, _ in steps)
    issues.extend(
        FlowPortIssue(problem=FlowPortProblem.SHARED_TRANSITION, hog_function_id=None, detail=transition)
        for transition, count in shared.items()
        if count > 1
    )

    masking_log = PlaceholderLog()
    masking = _ported_masking(enabled, masking_log) if enabled else None
    rewritten.extend(masking_log.rewritten)
    issues.extend(_unknown_placeholders(masking_log, None))
    if isinstance(masking, FlowPortIssue):
        issues.append(masking)
        masking = None

    flow = None
    if not issues and configuration_id is not None:
        flow = _flow(
            alert_name=alert_name,
            configuration_id=configuration_id,
            template_id=group[0].template_id or "",
            steps=steps,
            masking=masking,
        )
    return FlowPort(
        alert_id=alert_id,
        configuration_id=configuration_id,
        hog_function_ids=tuple(function.id for function in group),
        template_id=group[0].template_id,
        bucket=bucket,
        rewrites=tuple(dict.fromkeys(rewritten)),
        issues=tuple(dict.fromkeys(issues)),
        left_out=tuple(function.id for function in group if not function.enabled),
        flow=flow,
        secret_input_keys=secret_input_keys,
    )


def flow_ports(
    *,
    team_id: int,
    alerts: Iterable[NamedAlert],
    allowed_event_ids: Collection[str],
    transition_by_event_id: Mapping[str, AlertEventKind],
) -> Iterator[FlowPort]:
    """Each customized destination of the given alerts, with its workflow or what stops it."""
    names = {alert.alert_id: alert.name for alert in alerts}
    alert_ids = list(names)
    configuration_ids = configuration_ids_by_legacy_id(
        team_id=team_id, legacy_configuration_ids=[UUID(alert_id) for alert_id in alert_ids]
    )
    eligibilities_by_alert = classify_destinations_by_alert(
        team_id=team_id, alert_ids=alert_ids, allowed_event_ids=allowed_event_ids
    )
    functions = list(
        owned_alert_destinations_qs(
            team_id=team_id, alert_ids=alert_ids, allowed_event_ids=allowed_event_ids, known_templates_only=False
        )
        .filter(**RECEIVES_ALERT_EVENTS)
        .only("id", "template_id", "inputs", "encrypted_inputs", "filters", "masking", "enabled")
    )
    for alert_id in alert_ids:
        eligibilities = {eligibility.hog_function_id: eligibility for eligibility in eligibilities_by_alert[alert_id]}
        # A function saved after the classification has no eligibility yet, and the next run reports it.
        own = {
            function.id: function
            for function in functions
            if function.id in eligibilities and alert_id in named_alert_ids(function.filters)
        }
        groups = group_alert_destination_rows(
            [
                AlertDestinationRow(
                    function.id, function.template_id, stored_inputs(function.inputs, function.encrypted_inputs)
                )
                for function in own.values()
            ]
        )
        for ids in groups.values():
            group = [own[function_id] for function_id in sorted(ids)]
            bucket = most_restrictive(bucket_for(eligibilities[function.id]) for function in group)
            if bucket in _NATIVE_BUCKETS:
                continue
            yield _port(
                alert_id=alert_id,
                alert_name=names[alert_id],
                configuration_id=configuration_ids.get(UUID(alert_id)),
                group=group,
                eligibilities=eligibilities,
                bucket=bucket,
                transition_by_event_id=transition_by_event_id,
            )


def _names_configuration(trigger: Mapping[str, Any], configuration_ids: set[str]) -> bool:
    properties = (trigger.get("filters") or {}).get("properties") or []
    return any(
        isinstance(prop, dict)
        and prop.get("key") == "alert_configuration_id"
        and not configuration_ids.isdisjoint(prop.get("value") or ())
        for prop in properties
    )


def _drafts_refusal(team_id: int, ports: tuple[FlowPort, ...]) -> str | None:
    if any(port.flow is None for port in ports):
        return "A destination cannot become a workflow."
    configuration_ids = {port.configuration_id for port in ports if port.configuration_id is not None}
    if not configuration_ids:
        return None
    # The HogFlow API runs this check on every save, and the draft is saved without it.
    refusal = workflow_trigger_refusal(
        team_id=team_id, configuration_ids=configuration_ids, user_access_control=None, token_scopes=None
    )
    if refusal is not None:
        return refusal
    named = {str(configuration_id) for configuration_id in configuration_ids}
    existing = [
        workflow.id
        for workflow in workflows_for_origin(team_id=team_id, origin_product=HogFlowOriginProduct.ALERTS)
        if _names_configuration(workflow.trigger, named)
    ]
    if existing:
        return f"The alert already has workflows ({', '.join(map(str, existing))}). Delete them first."
    return None


def create_flow_drafts(
    *,
    team_id: int,
    alert: NamedAlert,
    allowed_event_ids: Collection[str],
    transition_by_event_id: Mapping[str, AlertEventKind],
) -> FlowDrafts:
    """Creates a draft workflow for each customized destination of one alert, and leaves its HogFunctions as they are.

    Nothing is created when any destination is stopped, when the alert has workflows from an earlier run, or when
    Workflows refuses the trigger or a secret.
    """
    ports = tuple(
        flow_ports(
            team_id=team_id,
            alerts=[alert],
            allowed_event_ids=allowed_event_ids,
            transition_by_event_id=transition_by_event_id,
        )
    )
    refusal = _drafts_refusal(team_id, ports)
    if refusal is not None:
        return FlowDrafts(ports=ports, refusal=refusal)
    try:
        with transaction.atomic():
            created = tuple(
                create_draft_workflow(
                    team_id=team_id,
                    user_id=None,
                    content=port.flow,
                    origin_product=HogFlowOriginProduct.ALERTS,
                    secret_input_keys=port.secret_input_keys,
                )
                for port in ports
                if port.flow is not None
            )
    except DraftWorkflowRefused as error:
        return FlowDrafts(ports=ports, refusal=str(error))
    return FlowDrafts(ports=ports, workflow_ids=created)


def _printable(text: str) -> str:
    # Details come from a team's own templates and filters, so a newline in one could forge a report line.
    return "".join(char if char.isprintable() else repr(char)[1:-1] for char in text)


def flow_port_report_lines(ports: Iterable[FlowPort]) -> Iterator[str]:
    """One line per destination, a line per rewrite and per issue, then the counts. Never an input value."""
    counts: Counter[str] = Counter()
    for port in ports:
        result = "ported" if port.flow is not None else "stopped"
        counts[result] += 1
        parts = [
            f"alert={port.alert_id}",
            f"destination={','.join(str(function_id) for function_id in port.hog_function_ids)}",
            f"template={port.template_id}",
            f"bucket={port.bucket}",
            f"result={result}",
        ]
        if port.flow is not None:
            parts.append(f"steps={sum(action['type'] == 'function' for action in port.flow['actions'])}")
        if port.left_out:
            parts.append(f"left_out={','.join(str(function_id) for function_id in port.left_out)}")
        yield " ".join(parts)
        for rewrite in port.rewrites:
            yield f"  rewrite {_printable(rewrite)}"
        for issue in port.issues:
            detail = f" detail={_printable(issue.detail)}" if issue.detail else ""
            yield f"  issue {issue.problem} function={issue.hog_function_id or '-'}{detail}"
    yield f"Destinations: ported={counts['ported']} stopped={counts['stopped']}"
