# Live Investigation Primitive — Design

**Status:** Draft
**Author:** Roy Cohen
**Date:** 2026-05-14
**Branch:** `hackathon-live-debugger-agent-tools` (current direction is to replace its contents with this design)

---

## Summary

A general-purpose, AI-native primitive that lets any PostHog agent install a hogtrace
program against a hypothesis, wait durably for probe data to accumulate over hours or
days, and produce a structured findings document — without that agent staying alive
across the wait. The primitive turns "install probe, wait, analyze, clean up" into a
single Temporal-backed resource that survives worker restarts, agent eviction, and
operator intervention, and whose findings are first-class durable output that downstream
consumers (PostHog Code, ticket systems, notebooks) can act on.

---

## Context & motivation

PostHog wants a proactive product loop: an error or anomaly is detected → an
investigation agent runs → if the agent can't conclude from existing data, it
instruments a live breakpoint to gather runtime evidence → findings flow into
downstream actions (a Task that PostHog Code picks up, a notebook entry, a
notification).

Two prior implementations on adjacent branches each took the wrong shape for this
loop:

- A child Temporal workflow that owned install/poll/uninstall as a self-contained
  unit. Lifecycle was right, but it was invoked imperatively rather than agentically
  and re-implemented operations that exist as MCP tools.
- Python tools on the anomaly investigation toolkit that installed and polled events
  inline within a single 20-minute activity. Followed established patterns but the
  time horizon and ownership model are wrong: real probe data often takes hours to
  accumulate, and the agent shouldn't babysit lifecycle.

This design replaces both with a primitive whose **lifecycle is owned by a durable
workflow, whose context flow between agent runs is a structured handoff (not a
replayed conversation), and whose tool surface is shared by every consumer**.

### Failure modes the design addresses

| Failure mode | How the design handles it |
|---|---|
| Probe data takes hours; agent can't wait | Workflow parks on `wait_condition`; agent fires and forgets |
| Worker crashes during the wait | Temporal durable wait survives worker death |
| Agent forgets to uninstall | Workflow `finally` block uninstalls unconditionally |
| Initial params (min_events, max_duration) were wrong | Workflow accepts `extend` / `analyze_now` signals while parked |
| Analysis runs but evidence is insufficient | Followup agent can chain a child investigation via the same start tool |
| Followup analysis activity crashes | Reconciliation sweeper recovers wedged rows |
| Multiple agents want to use this capability | Single Python facade + MCP tool surface, both delegating to the same machinery |

---

## Goals

1. Any PostHog agent — anomaly investigation, error tracking, oncall, PostHog Code, future ones — can start a live investigation through the same surface.
2. Investigations are **durable** across worker restarts, agent eviction, and process boundaries. The agent that starts an investigation does not need to stay alive to see it through.
3. Findings are **structured Pydantic output** ready for downstream consumption (Tasks, notebooks, notifications).
4. The agent loop never holds LLM conversation state — only references to brief and findings rows.
5. Investigations are **recursive**: a followup agent can chain a child investigation when its hypothesis was wrong or evidence was insufficient. Bounded by a chain-depth cap.
6. Operators can `extend`, `analyze_now`, or `close` a running investigation without code changes.

## Non-goals

- A UI for live investigations. v1 is purely backend + API; UI is a separate effort.
- Cross-team investigations. Each investigation is team-scoped.
- Multi-program investigations (a single investigation managing multiple programs in parallel). v1 is one program per investigation; chained investigations cover the multi-probe case.
- Migrating other PostHog AI workflows away from their existing toolkits. Anomaly investigation gains a new tool; other workflows are unchanged.
- Tasks integration. Findings are structured and ready; the glue that turns a finding into a Task lives downstream of this primitive and is out of scope (see *Downstream integration points*).

---

## Architecture overview

### Components

```
products/live_debugger/backend/
    models.py
        LiveDebuggerProgram          (existing — hogtrace program rows)
        LiveInvestigation            (NEW — links a program to a signal source + brief + findings)
    facade/api.py
        start_live_investigation()   (NEW — public Python entry point)
    api.py
        LiveInvestigationViewSet     (NEW — REST surface for MCP)
    serializers.py
        LiveInvestigationSerializer  (NEW)
    mcp/tools.yaml
        live-investigation-start     (NEW)
        live-investigation-get       (NEW)
        live-investigation-list      (NEW)

posthog/temporal/ai/live_investigation/
    workflow.py                       LiveInvestigationWorkflow (Temporal — durable lifecycle)
    activities.py                     analyze_live_investigation_activity,
                                      uninstall_program_activity,
                                      mark_investigation_cancelled_activity
    runner.py                         Followup-agent tool loop
    prompts.py                        Followup-agent system prompt
    schemas.py                        LiveInvestigationBrief, LiveInvestigationFindings (Pydantic)
    tools.py                          Toolkit for the followup agent

posthog/tasks/
    live_investigations.py            check_ready_investigations() Celery beat
                                      reconcile_stuck_investigations() sweeper
```

### Happy-path data flow

```
[1] Signal source fires (anomaly alert, error tracking issue, oncall, manual…)

[2] Calling agent runs in its own activity (e.g. investigate_anomaly_activity).
    Analyses existing data, decides: "I need runtime evidence to confirm hypothesis H."

[3] Calling agent invokes the start tool, which calls the facade:
    start_live_investigation(
        team, signal_source_type="anomaly_alert", signal_source_id=str(alert_check.id),
        args=StartLiveInvestigationArgs(
            hogtrace_code=...,
            brief=LiveInvestigationBrief(hypothesis, what_to_look_for, ...),
            min_events=20,
            max_duration_minutes=120,
        ),
    )
    Facade:
      - Validates chain_depth against MAX_CHAIN_DEPTH.
      - Creates LiveDebuggerProgram (status=INSTALLED).
      - Creates LiveInvestigation row (status=WATCHING, brief=..., program FK).
      - Starts LiveInvestigationWorkflow with the investigation_id (on_commit).
    Returns investigation_id to the calling agent.

[4] Calling agent's own work ends. It writes its in-flight findings to its
    own notebook with a "watching for runtime evidence; investigation id=…" note.

[5] [hours pass] LiveInvestigationWorkflow is parked on:
        wait_condition(lambda: self._events_ready or self._force_analyze or self._closed,
                       timeout=max_duration + extensions)

[6] Celery beat (every ~30s):
      - Scans LiveInvestigation rows where status=WATCHING.
      - Counts events per program in ClickHouse, batched per team.
      - For each row whose program has count >= min_events, signals the workflow
        with events_ready.

[7] Workflow wakes. Executes analyze_live_investigation_activity:
      - Activity flips row status WATCHING → ANALYZING.
      - Loads brief + accumulated probe events from ClickHouse (summarized).
      - Runs a fresh Claude tool-loop (followup agent) primed with brief + events.
      - Agent emits a LiveInvestigationFindings doc.
      - Activity persists findings, flips row status ANALYZING → COMPLETE.

[8] Workflow's `finally` block executes uninstall_program_activity.
    LiveDebuggerProgram status flips INSTALLED → UNINSTALLED.

[9] Findings are durable. Downstream consumers (notebook renderer, Task creator,
    notification dispatcher) read them when they want.
```

### Key invariants

- **The Temporal workflow never holds LLM state.** Conversation lives only inside `analyze_live_investigation_activity`. The workflow holds only `_events_ready: bool`, `_force_analyze: bool`, `_closed: bool`, `_deadline_extensions_seconds: int`.
- **No agent waits in real-time for events.** The calling agent fires-and-forgets. The workflow parks via Temporal's durable wait.
- **The brief is the only thing that crosses agent-run boundaries.** No conversation replay. The followup agent starts a fresh conversation primed with brief + events.
- **Cleanup is the workflow's responsibility, not the agent's.** Whether analysis succeeds, fails, or times out, the workflow uninstalls the program in a Temporal `try/finally`.
- **The primitive is closed under composition.** Calling agent and followup agent share the same `start_live_investigation` surface. There is no distinguished "first" or "followup" investigation in the data model — only `parent_investigation_id` links.

---

## Data model

Two new pieces — a Django model and two Pydantic schemas stored as `JSONField`s on it.

### `LiveInvestigation` (Django, `products/live_debugger/backend/models.py`)

```python
class LiveInvestigation(UUIDModel):
    class Status(models.TextChoices):
        WATCHING = "watching", "Watching"      # Program installed, workflow parked
        ANALYZING = "analyzing", "Analyzing"   # events_ready fired, analysis running
        COMPLETE = "complete", "Complete"      # Findings written, program uninstalled
        CANCELLED = "cancelled", "Cancelled"   # close signal received before analysis

    team = FK("posthog.Team", on_delete=CASCADE)
    program = FK(LiveDebuggerProgram, on_delete=PROTECT, related_name="investigations")
    parent = FK("self", null=True, on_delete=SET_NULL, related_name="children")
    chain_depth = PositiveIntegerField(default=0)

    status = CharField(choices=Status.choices, default=Status.WATCHING)
    workflow_id = CharField(max_length=255)              # Temporal workflow ID for signaling

    min_events = PositiveIntegerField()
    max_duration_seconds = PositiveIntegerField()

    # Free-form pointer to where this came from
    signal_source_type = CharField(max_length=64)        # "anomaly_alert", "error_tracking_issue", "manual", ...
    signal_source_id = CharField(max_length=128, blank=True)

    brief = JSONField()                                  # LiveInvestigationBrief shape
    findings = JSONField(null=True)                      # LiveInvestigationFindings shape

    created_at = DateTimeField(auto_now_add=True)
    completed_at = DateTimeField(null=True)

    class Meta:
        db_table = "posthog_liveinvestigation"
        indexes = [
            Index(fields=["status"], name="live_inv_status_idx"),
            Index(fields=["team_id", "status"], name="live_inv_team_status_idx"),
            Index(fields=["program_id"], name="live_inv_program_idx"),
        ]
```

**Field rationale:**

- `program` uses `PROTECT` — investigations reference the program forever in their findings; deleting the program would orphan evidence. Programs are soft-uninstalled, never deleted.
- `parent` uses `SET_NULL` — deleting an old root doesn't cascade-kill the chain.
- `workflow_id` is required so anything in PostHog (UI button, calling agent, Celery beat) can `client.get_workflow_handle(workflow_id).signal(...)`.
- `signal_source_type` + `signal_source_id` are plain strings, not a `GenericForeignKey`. ContentTypes adds a join the followup agent never needs — the agent reads `brief.signal_summary` for context. The string fields are for humans auditing later.
- `chain_depth` is materialized so the facade can cap-check via index lookup rather than recursive CTE.

### `LiveInvestigationBrief` (Pydantic, `posthog/temporal/ai/live_investigation/schemas.py`)

The handoff doc the calling agent writes when starting an investigation.

```python
class LiveInvestigationBrief(BaseModel):
    hypothesis: str = Field(description="One-sentence hypothesis the probes are meant to confirm or refute.")
    what_to_look_for: list[str] = Field(
        description="Specific patterns in probe events that would support or refute the hypothesis. "
                    "Concrete and observable — 'session_id is non-null but user_id is null', "
                    "not 'something is off in auth'."
    )
    instrumentation_rationale: str = Field(
        description="Why probes are placed where they are. The followup agent reads this to understand "
                    "what the calling agent expected to see, so it can recognize when reality diverges."
    )
    signal_summary: str = Field(
        description="What triggered this investigation. Free-form summary of the originating signal — "
                    "preserves context that doesn't live in PostHog."
    )
    parent_summary: str | None = Field(
        default=None,
        description="Set when this investigation is a chained followup. The parent investigation's "
                    "findings summary, so this run knows what its predecessor concluded.",
    )
```

### `LiveInvestigationFindings` (Pydantic, same file)

What the followup agent emits as structured output.

```python
class LiveInvestigationFindings(BaseModel):
    status: Literal["definitive", "needs_more_data", "needs_different_probe",
                    "spawned_followup", "gave_up"]
    summary: str = Field(description="1–3 sentence plain-English conclusion.")
    confidence: float = Field(ge=0.0, le=1.0, description="Agent's self-assessed confidence.")
    evidence_event_ids: list[str] = Field(
        default_factory=list,
        description="UUIDs of probe events that drove the conclusion. Used by downstream "
                    "renderers to link back to raw evidence.",
    )
    hypothesis_outcome: Literal["confirmed", "refuted", "partial", "unrelated", "inconclusive"]
    next_step_rationale: str | None = Field(
        default=None,
        description="Required when status is needs_more_data, needs_different_probe, or spawned_followup.",
    )
    spawned_followup_id: UUID | None = Field(
        default=None,
        description="Set when status=spawned_followup. The child LiveInvestigation.id the agent created.",
    )
```

The `findings.status` discriminator captures the *quality* of the conclusion. The row's `status` field captures only *workflow lifecycle*. `COMPLETE` doesn't imply "we got a good answer"; it implies "the workflow finished and findings are written."

---

## Workflow & state machine

### Temporal workflow skeleton

```python
@workflow.defn(name="live-investigation")
class LiveInvestigationWorkflow(PostHogWorkflow):
    def __init__(self) -> None:
        self._events_ready: bool = False
        self._force_analyze: bool = False
        self._closed: bool = False
        self._deadline_extensions_seconds: int = 0

    @workflow.signal
    async def events_ready(self) -> None:
        self._events_ready = True

    @workflow.signal
    async def extend(self, extra_seconds: int) -> None:
        self._deadline_extensions_seconds = min(
            self._deadline_extensions_seconds + extra_seconds,
            MAX_EXTENSION_SECONDS,
        )

    @workflow.signal
    async def analyze_now(self) -> None:
        self._force_analyze = True

    @workflow.signal
    async def close(self) -> None:
        self._closed = True

    @workflow.run
    async def run(self, input: LiveInvestigationWorkflowInput) -> None:
        try:
            try:
                await workflow.wait_condition(
                    lambda: self._events_ready or self._force_analyze or self._closed,
                    timeout=timedelta(
                        seconds=input.max_duration_seconds + self._deadline_extensions_seconds
                    ),
                )
            except TimeoutError:
                pass  # treated same as events_ready=False — analyze with whatever we have

            if self._closed:
                await workflow.execute_activity(
                    mark_investigation_cancelled_activity,
                    input.investigation_id,
                    start_to_close_timeout=timedelta(seconds=30),
                )
                return

            await workflow.execute_activity(
                analyze_live_investigation_activity,
                AnalyzeInput(investigation_id=input.investigation_id),
                start_to_close_timeout=timedelta(seconds=ANALYZE_ACTIVITY_TIMEOUT_SECONDS),
                heartbeat_timeout=timedelta(seconds=ANALYZE_ACTIVITY_HEARTBEAT_SECONDS),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        finally:
            await workflow.execute_activity(
                uninstall_program_activity,
                input.program_id,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
                cancellation_type=ActivityCancellationType.ABANDON,
            )
```

### State machine (DB row)

```
WATCHING ──(events_ready | analyze_now | timeout)──→ ANALYZING ──→ COMPLETE
   │
   └────────────(close)─────────────────────────────────────────→ CANCELLED
```

Transitions happen *inside activities*, not in workflow code (workflow code must be deterministic; DB writes aren't).

### Constants

```python
ANALYZE_ACTIVITY_TIMEOUT_SECONDS = 20 * 60     # 20 min for the agent loop
ANALYZE_ACTIVITY_HEARTBEAT_SECONDS = 5 * 60    # matches anomaly_investigation pattern
MAX_EXTENSION_SECONDS = 24 * 3600              # 24h absolute cap on cumulative extensions
MAX_CHAIN_DEPTH = 3                            # facade-enforced
```

### Failure handling

| Failure | What happens |
|---|---|
| `analyze_live_investigation_activity` fails on attempt 1 | Retried up to 2 attempts. If both fail, the workflow proceeds to `finally` (program uninstalled). Row left in `ANALYZING` until reconciliation sweeper recovers it. |
| `uninstall_program_activity` fails after retries | Reconciliation sweeper finds programs still `INSTALLED` past their owning investigation's `completed_at` and uninstalls them. |
| Workflow worker crashes mid-`wait_condition` | Temporal handles transparently — durable wait survives worker death. |
| Workflow force-cancelled by operator | `finally` block still runs. `uninstall_program_activity` uses `ActivityCancellationType.ABANDON` so workflow cancellation doesn't cancel the in-flight uninstall. |
| `events_ready` signal fires before workflow exists | Temporal buffers signals to a workflow that hasn't yet started. Facade creates row and starts workflow in the same transaction, so this is theoretical. |
| Deadline extensions signaled forever | `MAX_EXTENSION_SECONDS` cap bounds absolute lifetime. |

### Why `cancellation_type=ActivityCancellationType.ABANDON` on uninstall

If the workflow is cancelled while uninstall is in flight, the default is for Temporal to also cancel the uninstall. That defeats the purpose — uninstalling a live program is the entire point of cleanup. `ABANDON` lets it finish independently.

### Why `analyze` is one activity, not many

The followup agent's tool-calling loop *could* be modeled as one Temporal activity per tool call, with the workflow holding the conversation. This is over-engineered: each tool call would add Temporal overhead, and conversation state would have to be serialized into workflow state (breaking the rule "workflow never holds LLM state"). The existing `anomaly_investigation` pattern — one activity owns the whole agent loop — is correct here.

---

## Surfaces — Python facade + MCP tools

The primitive is exposed through **two parallel surfaces** that both delegate to the same facade. This is the key change that makes the primitive *actually* general-purpose: any in-process Python consumer can call the facade directly; any out-of-process / sandboxed consumer (notably PostHog Code) reaches it over MCP.

### Python facade — in-process consumers

```python
# products/live_debugger/backend/facade/api.py

class StartLiveInvestigationArgs(BaseModel):
    hogtrace_code: str
    brief: LiveInvestigationBrief
    min_events: int = Field(default=20, ge=1, le=500)
    max_duration_minutes: int = Field(default=120, ge=5, le=24 * 60)
    parent_investigation_id: UUID | None = None


async def start_live_investigation(
    team: Team,
    signal_source_type: str,
    signal_source_id: str,
    args: StartLiveInvestigationArgs,
) -> str:
    """Single source of truth for starting an investigation. Returns investigation_id."""
    # 1. Validate chain_depth if parent_investigation_id is set
    # 2. Inside transaction.atomic():
    #    - Create LiveDebuggerProgram (status=INSTALLED)
    #    - Create LiveInvestigation row (status=WATCHING)
    # 3. transaction.on_commit(start_workflow)
    # 4. Return investigation_id
```

This is the entry point internal consumers use. Anomaly investigation's `InvestigationToolkit` wraps it as a tool:

```python
# Inside posthog/temporal/ai/anomaly_investigation/tools.py
async def start_live_investigation(self, args: StartLiveInvestigationArgs) -> str:
    investigation_id = await live_debugger_facade.start_live_investigation(
        team=self.team,
        signal_source_type="anomaly_alert",
        signal_source_id=str(self.alert.id) if self.alert else "",
        args=args,
    )
    return json.dumps({"investigation_id": investigation_id, "status": "watching"})
```

### MCP tools — out-of-process consumers

Three new MCP tools in `products/live_debugger/mcp/tools.yaml`, each backed by a `LiveInvestigationViewSet` method that delegates to the facade.

```yaml
live-investigation-start:
    operation: live_investigation_create
    scopes: [live_debugger:write]
    annotations:
        readOnly: false
        destructive: false
    title: Start live investigation
    description: >
        Start a durable live investigation. Installs a hogtrace program with a
        hypothesis brief, watches for probe events up to max_duration, then runs
        a followup agent to analyze findings. Returns immediately with the
        investigation_id; findings are available later via live-investigation-get.

live-investigation-get:
    operation: live_investigation_retrieve
    scopes: [live_debugger:read]
    annotations: { readOnly: true, idempotent: true }
    title: Get live investigation
    description: >
        Get a live investigation by id, including its status (watching, analyzing,
        complete, cancelled) and findings (when complete).

live-investigation-list:
    operation: live_investigation_list
    scopes: [live_debugger:read]
    annotations: { readOnly: true, idempotent: true }
    title: List live investigations
    description: >
        List recent live investigations for the project, most recent first.
        Useful for "do I have findings yet?" checks during a long-running task.
```

### Backing API

```python
# products/live_debugger/backend/api.py
class LiveInvestigationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    serializer_class = LiveInvestigationSerializer
    queryset = LiveInvestigation.objects.all()
    scope_object = "live_debugger"

    def create(self, request):
        # Parse StartLiveInvestigationArgs, call facade, return serialized row
        ...

    def retrieve(self, request, pk):
        # Vanilla DRF retrieve
        ...

    def list(self, request):
        # Most-recent-first, paginated
        ...
```

```python
# products/live_debugger/backend/serializers.py
class LiveInvestigationSerializer(serializers.ModelSerializer):
    brief = serializers.JSONField(help_text="LiveInvestigationBrief schema")
    findings = serializers.JSONField(help_text="LiveInvestigationFindings schema; null while watching/analyzing")
    program_id = serializers.UUIDField(source="program.id", read_only=True)

    class Meta:
        model = LiveInvestigation
        fields = ["id", "status", "brief", "findings", "program_id",
                  "min_events", "max_duration_seconds",
                  "signal_source_type", "signal_source_id",
                  "parent", "chain_depth", "created_at", "completed_at"]
        read_only_fields = ["id", "status", "findings", "chain_depth", "completed_at", "created_at"]
```

### Why two surfaces

Without the MCP surface, the "general-purpose primitive" claim is partial: only anomaly investigation (and other in-process Python callers) can use it. PostHog Code runs in a sandbox and talks to PostHog over HTTP/MCP; without an MCP tool, it would have to manually replicate the install/poll/uninstall pattern using the existing program-level MCP tools, missing out on durability, structured findings, chain bookkeeping, and the followup agent.

The two surfaces share one backend. The viewset is a thin delegator. The facade is the contract.

---

## Agent runtime — calling agent + followup agent

### Calling agent — one tool

Any agent (anomaly investigation's `InvestigationToolkit`, future agents) gets a single tool. The calling agent never sees programs, workflows, signals — only "I started investigation X, it'll have findings later."

```python
# Anomaly toolkit example
async def start_live_investigation(self, args: StartLiveInvestigationArgs) -> str: ...
```

For PostHog Code or other out-of-process agents, the equivalent is the MCP tool `live-investigation-start`.

### Followup agent — runs inside `analyze_live_investigation_activity`

Structurally a sibling of `investigate_anomaly_activity`: fetches state, runs a Claude tool loop, persists findings. Lives at `posthog/temporal/ai/live_investigation/runner.py`.

**Context priming** — built before the loop starts:

```python
messages = [
    SystemMessage(content=LIVE_INVESTIGATION_FOLLOWUP_PROMPT),
    HumanMessage(content=[
        {"type": "text", "text": _render_brief(investigation.brief)},
        {"type": "text", "text": _render_parent_summary(investigation.parent)},
        {"type": "text", "text": _summarize_program_events(events_loaded_from_clickhouse)},
    ]),
]
```

The agent starts cold (no prior conversation), but with the brief, the parent's summary if chained, and the aggregated probe events all already in context. No "discover the events" round-trip.

**Tools available** to the followup agent:

```python
@dataclass
class LiveInvestigationToolkit:
    team: Team
    investigation: LiveInvestigation
    events: list[ProgramEvent]  # pre-loaded
    heartbeat: Callable[[], None] | None = None

    async def get_event_detail(self, args: GetEventDetailArgs) -> str:
        """Drill into a specific event the agent wants to inspect in detail."""

    async def run_hogql_query(self, args: RunHogQLQueryArgs) -> str:
        """General data queries — for 'does this hit correlate with a deploy / property X?'"""

    async def start_live_investigation(self, args: StartLiveInvestigationArgs) -> str:
        """Chain a followup. Same tool the calling agent had."""
```

**No installation/uninstallation tools.** The followup agent never owns program lifecycle — the workflow does. To get more data, the agent chains via `start_live_investigation`; the workflow cleans up the current investigation regardless.

**Structured output** — the agent's final message must be a `LiveInvestigationFindings` JSON. Same parse pattern as `InvestigationReport._parse_report` in anomaly investigation. If output is unparseable, the activity falls back to `status=gave_up, summary="agent emitted unparseable output"`.

### Why this carve-up matters

- **Symmetric chaining**: calling agent and followup agent both have `start_live_investigation`. Same tool, same args, same semantics. Recursion is real and uniform.
- **Followup doesn't have to discover its own context**: brief and events are *in the prompt*, not behind tools. Tool calls are reserved for verification and chaining decisions.
- **Workflow owns lifecycle, agent owns analysis**: clean separation. The agent never sees the program ID it's analyzing — it can read it from the investigation row metadata but can't act on it directly. Operationally safer.

---

## Events-ready detector — Celery beat

The piece that wakes parked workflows when probe data has accumulated. Celery beat, lives in `posthog/tasks/live_investigations.py`.

### Beat task

```python
@shared_task(
    name="posthog.tasks.live_investigations.check_ready_investigations",
    soft_time_limit=120,
    time_limit=180,
    rate_limit="2/m",
)
def check_ready_investigations() -> None:
    asyncio.run(_check_ready_investigations_async())


async def _check_ready_investigations_async() -> None:
    rows = await sync_to_async(_load_watching_investigations, thread_sensitive=False)()
    if not rows:
        return

    # Group by team — one HogQL count per team rather than per program.
    by_team: dict[int, list[LiveInvestigation]] = defaultdict(list)
    for row in rows:
        by_team[row.team_id].append(row)

    temporal_client = await get_temporal_client()

    for team_id, investigations in by_team.items():
        try:
            counts = await _count_events_per_program(team_id, investigations)
        except Exception:
            logger.exception("live_investigations.count_failed", extra={"team_id": team_id})
            continue

        for inv in investigations:
            if counts.get(str(inv.program_id), 0) >= inv.min_events:
                try:
                    handle = temporal_client.get_workflow_handle(inv.workflow_id)
                    await handle.signal("events_ready")
                except Exception:
                    logger.exception(
                        "live_investigations.signal_failed",
                        extra={"investigation_id": str(inv.id)},
                    )
```

### Count query

Single HogQL query per team. One ClickHouse scan per team per beat run, regardless of how many investigations that team has running.

```sql
SELECT JSONExtractString(properties, '$program_id') AS pid, count() AS c
FROM events
WHERE event = '$data_breakpoint_hit'
  AND JSONExtractString(properties, '$program_id') IN {program_ids}
GROUP BY pid
```

### Why beat (not workflow self-poll)

| | Beat | Workflow self-poll |
|---|---|---|
| Per-program query | 1 batched query per team per cycle | 1 query per program per cycle |
| Throttling lever | Single knob (beat interval) | Per-workflow config |
| Workflow code | Simple wait | Workflow holds poll loop, more replay state |
| Failure isolation | Beat crash → timeout fallback in workflow | Same |

The beat wins on batching and centralized throttling. Workflow self-poll wins on independence — but the workflow's `wait_condition` timeout already provides that as a fallback. If the beat is down for 20 minutes, every `WATCHING` investigation older than its `max_duration` will time out naturally and analyze with whatever it has.

### Idempotency

- **Signal idempotency**: `events_ready` handler sets `self._events_ready = True`. Calling it 50 times is harmless. After the workflow wakes and the row transitions to `ANALYZING`, the next beat run won't pick it up (status filter excludes it).
- **Beat collisions**: Celery `rate_limit="2/m"` plus singleton beat scheduling prevent overlapping runs in practice. If they happen anyway, idempotent signaling makes it safe.
- **Beat-vs-timeout race**: Both unblock the same `wait_condition` predicate; the workflow runs `analyze` once.

### Reconciliation sweeper

Same file, scheduled every 5 min:

```python
@shared_task(name="posthog.tasks.live_investigations.reconcile_stuck_investigations")
def reconcile_stuck_investigations() -> None:
    """Recover rows wedged in ANALYZING (analyze activity crashed past retry budget)
    or programs left INSTALLED past their owning investigation's completed_at."""
```

Handles the edge cases listed in the workflow failure table.

### Telemetry (v1)

Three structured logs:
- `live_investigations.beat_run` per cycle: `{scanned: N, signaled: M, errors: K}`
- `live_investigations.signal_sent` per signal: `{investigation_id, event_count}`
- `live_investigations.signal_failed` on error

No Prometheus metrics in v1 — counts derivable from logs. Add metrics later if the beat becomes load-bearing.

---

## Self-correction — chained investigations

When an investigation's findings indicate the initial hypothesis was wrong or evidence was insufficient, the followup agent can spawn a child investigation via the same `start_live_investigation` tool. The child carries `parent_investigation_id` and `chain_depth = parent.chain_depth + 1`.

The facade caps `chain_depth` at `MAX_CHAIN_DEPTH = 3`. If a 4th-generation child is attempted, the facade refuses and the agent must wrap up.

`findings.status` is a discriminator that explicitly tells downstream consumers what kind of conclusion this is:
- `definitive` — conclusion reached, no further action needed
- `needs_more_data` — same probe, more time/hits required (operator can `extend`)
- `needs_different_probe` — hypothesis was wrong, different instrumentation needed (operator or agent can chain)
- `spawned_followup` — agent already chained; see `spawned_followup_id`
- `gave_up` — agent could not produce a useful conclusion

This is **post-flight** self-correction. **Mid-flight** self-correction is via the `extend`, `analyze_now`, and `close` workflow signals — they let any actor (human via CLI, agent that's still alive, future UI button) adjust an investigation's deadline or force-trigger analysis without waiting for the natural cadence.

---

## Testing strategy

Six layers, sized to verify the invariants without over-testing.

### 1. Model & facade tests — `products/live_debugger/backend/test_live_investigation.py`

```python
@pytest.mark.django_db(transaction=True)
class TestStartLiveInvestigation:
    async def test_creates_program_and_investigation_in_one_transaction(self, team): ...
    async def test_returns_investigation_id(self, team): ...
    async def test_starts_temporal_workflow_with_investigation_id(self, team): ...
    async def test_chain_depth_zero_for_root(self, team): ...
    async def test_chain_depth_incremented_for_child(self, team): ...
    async def test_refuses_child_at_max_chain_depth(self, team): ...
    async def test_rollback_on_workflow_start_failure(self, team): ...
```

### 2. Workflow state-machine tests — `posthog/temporal/tests/ai/test_live_investigation_workflow.py`

Uses Temporal's `WorkflowEnvironment` with time-skipping. Activities mocked to deterministic returns.

```python
class TestLiveInvestigationWorkflow:
    async def test_runs_analyze_then_uninstall_on_events_ready(self): ...
    async def test_runs_analyze_then_uninstall_on_analyze_now(self): ...
    async def test_runs_analyze_then_uninstall_on_timeout(self): ...
    async def test_skips_analyze_runs_uninstall_on_close(self): ...
    async def test_uninstall_runs_even_when_analyze_fails(self): ...
    async def test_extend_signal_pushes_deadline(self): ...
    async def test_extend_capped_at_max_extension_seconds(self): ...
    async def test_uninstall_uses_ABANDON_on_workflow_cancellation(self): ...
```

### 3. Activity tests — `posthog/temporal/tests/ai/test_live_investigation_activities.py`

```python
class TestAnalyzeLiveInvestigationActivity:
    async def test_persists_findings_to_row(self): ...
    async def test_transitions_row_watching_to_analyzing_to_complete(self): ...
    async def test_loads_brief_and_events_into_human_message(self): ...
    async def test_falls_back_to_gave_up_findings_on_unparseable_output(self): ...
    async def test_handles_zero_events_with_inconclusive_findings(self): ...

class TestUninstallProgramActivity:
    async def test_uninstalls_via_facade(self): ...
    async def test_is_idempotent(self): ...

class TestMarkInvestigationCancelledActivity:
    async def test_sets_status_to_cancelled(self): ...
```

### 4. Followup-agent runner tests — `posthog/temporal/tests/ai/test_live_investigation_runner.py`

Mock the LLM at the `MaxChatAnthropic` boundary. Same pattern as `test_anomaly_investigation_verdict.py`.

```python
class TestLiveInvestigationRunner:
    async def test_parses_findings_from_final_message(self): ...
    async def test_handles_tool_calls_within_budget(self): ...
    async def test_returns_gave_up_when_budget_exhausted_without_findings(self): ...
    async def test_chain_tool_invokes_facade_with_parent_id(self): ...
    async def test_unparseable_final_message_falls_back(self): ...
```

### 5. Beat tests — `posthog/tasks/test_live_investigations.py`

```python
class TestCheckReadyInvestigations:
    async def test_signals_investigations_at_or_above_min_events(self): ...
    async def test_skips_investigations_below_min_events(self): ...
    async def test_batches_counts_per_team(self): ...
    async def test_continues_on_per_team_count_failure(self): ...
    async def test_continues_on_per_investigation_signal_failure(self): ...
    async def test_ignores_non_watching_rows(self): ...

class TestReconcileStuckInvestigations:
    async def test_marks_stale_analyzing_rows_complete_with_gave_up(self): ...
    async def test_uninstalls_orphaned_installed_programs(self): ...
```

### 6. Viewset / MCP surface tests — `products/live_debugger/backend/test_live_investigation_api.py`

```python
class TestLiveInvestigationViewSet:
    def test_create_delegates_to_facade(self): ...
    def test_create_requires_write_scope(self): ...
    def test_retrieve_returns_brief_and_findings(self): ...
    def test_retrieve_requires_read_scope(self): ...
    def test_list_orders_most_recent_first(self): ...
    def test_cross_team_access_denied(self): ...
```

### 7. End-to-end test — `posthog/temporal/tests/ai/test_live_investigation_e2e.py`

The single test that exercises everything wired up. Real Postgres, real Temporal test environment, real ClickHouse fixtures, mocked LLM.

```python
class TestLiveInvestigationEndToEnd:
    async def test_full_lifecycle_with_real_workflow_and_mocked_llm(self):
        # 1. Call start_live_investigation facade
        # 2. Insert fake $data_breakpoint_hit events into ClickHouse
        # 3. Run beat task once
        # 4. Workflow wakes, runs analyze (LLM mocked to emit valid findings)
        # 5. Assert row.status == COMPLETE, findings set, program.status == UNINSTALLED
```

### Sizing

~45 tests total across seven files. Workflow tests are heavier (~30–50 lines each); facade, beat, and viewset tests are quick.

### Not tested in v1

- Network-level Temporal signal delivery (Temporal's concern, well-tested upstream)
- ClickHouse query correctness beyond fixture-driven smoke (real query patterns exercised by existing `LiveDebuggerProgram.get_program_events` tests)
- Concurrent beat runs (`rate_limit` + singleton scheduling make this a non-issue)
- Prompt quality / agent behavior (eval-suite territory)

---

## Downstream integration points (deferred)

These are intentionally **out of scope** for the v1 PRs but worth documenting so the contract is clear.

### Tasks integration

The proactive product loop completes when a `LiveInvestigationFindings.status == "definitive"` finding becomes a `Task` with `origin_product=LIVE_INVESTIGATION` (new enum value). PostHog Code picks the task up and opens a PR.

What's needed when this is built:
- A new `Task.OriginProduct.LIVE_INVESTIGATION` enum value (in `products/tasks/`)
- A signal handler or post-save hook on `LiveInvestigation` that, when transitioning to `COMPLETE` with `findings.status == "definitive"`, creates a Task with the findings summary as description, evidence event IDs in the body, and repository inferred from probe locations
- Probably feature-flagged initially

What's *not* needed (already provided by v1):
- Structured findings — `LiveInvestigationFindings` is the contract
- Auditable link back — `Task.live_investigation_id` would be a new FK; `LiveInvestigation.signal_source_type="task"` already supported for the reverse direction
- Repository resolution — probe events carry `filename`; either the findings agent specifies repository, or a downstream service infers it

### Other downstream surfaces

- **Notebooks**: an investigation's findings can render as a notebook section. Calling agents (anomaly) already write notebooks; a downstream renderer can pick up `findings.status=definitive` and append.
- **Notifications**: a sender service can fire a notification on `COMPLETE` with `confidence >= 0.7`.
- **Linear / external tickets**: any sender service can map `findings` to a ticket creation API.

The primitive provides the structured output; consumers choose what to do with it.

---

## Open questions / decisions to revisit

| Question | Current plan | Revisit when |
|---|---|---|
| Should the beat interval (30s) be a feature flag or constant? | Constant for v1 | First production tuning round |
| Should `MAX_CHAIN_DEPTH = 3` be per-team configurable? | Constant for v1 | First abuse / runaway incident, or feedback that 3 is too restrictive |
| Should findings include LLM token usage / cost? | Not in v1 (matches anomaly investigation) | When team-level cost attribution is needed |
| Should `LiveInvestigation` retention be capped (e.g. 90 days)? | Not in v1 (rows are small) | When the table outgrows expectations |
| Should we add Anthropic native MCP-client integration for the followup agent itself? | Not in v1 (in-process tool wrappers are simpler) | When PostHog has a unified internal MCP-as-client strategy |

---

## Migration path from current branches

- **Branch `hackathon-live-debugger-temporal`** (the original child-workflow approach): superseded entirely. Do not merge. Lessons applied: durable workflow is good, but lifecycle owner is the workflow not the agent; install/uninstall as MCP tools are the right primitive surface.
- **Branch `hackathon-live-debugger-agent-tools`** (the agent-toolkit refinement): superseded by this design. The `wait_and_collect_events` and `cleanup_installed_programs` mechanisms are dropped — they were the right shape for "agent owns lifecycle inside one activity," which is the wrong shape for proactive product. The pre-existing live debugger MCP tools (`live_debugger_programs_install/uninstall/events`) remain — they are still useful for direct probe-level operations.

## Open implementation order (sketch — will be elaborated in writing-plans)

1. **Foundation PR**: `LiveInvestigation` model + migration + Pydantic schemas + facade method (no workflow yet — facade returns a stubbed workflow_id).
2. **Workflow PR**: `LiveInvestigationWorkflow` + activities + the three signal handlers. Facade now starts a real workflow.
3. **Followup agent PR**: `runner.py` + `prompts.py` + `tools.py` + the `analyze_live_investigation_activity` integration.
4. **MCP surface PR**: viewset + serializer + `tools.yaml` entries + URL routing.
5. **Detector PR**: beat task + reconciliation sweeper.
6. **End-to-end test PR**: the single integration test that ties everything together.
7. **Anomaly integration PR**: anomaly toolkit gets the `start_live_investigation` tool.

Each PR is independently mergeable and has its own test slice. PRs 1–6 land machinery without any user-visible behavior, because no calling agent invokes the primitive until PR 7 wires anomaly investigation's toolkit to `start_live_investigation`.
