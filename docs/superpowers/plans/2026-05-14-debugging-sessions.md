# Debugging Sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wrap live_debugger agent investigations in a `DebuggingSession` whose ordered, typed entries (notes, program installs/uninstalls, event highlights, conclusion) render as a read-only notebook in the UI.

**Architecture:** Two new Postgres tables (`LiveDebuggerSession`, `LiveDebuggerSessionEntry`) and a nullable `session_id` FK on `LiveDebuggerProgram`. A single `LiveDebuggerSessionViewSet` exposes the session lifecycle as DRF `@action` methods. Old program-centric MCP tools are disabled; new session-scoped tools replace them. A new pair of frontend scenes lists sessions and renders a session's timeline as a stacked notebook.

**Tech Stack:** Django + DRF (backend), drf-spectacular + Orval (codegen), Kea + React + Tailwind (frontend), hogtrace/libdebugger (probe runtime).

**Spec:** `docs/superpowers/specs/2026-05-14-debugging-sessions-design.md`

**Scope reminder:** Hackathon demo. Optimize for "mostly works." Single-producer agent. Skip concurrency hardening, pagination, reopening, edit/delete, stale-session sweeping.

**Mandatory project skills the executor must invoke when touched:**

- `/django-migrations` — before writing the migration in Task 1.
- `/improving-drf-endpoints` — before editing serializers / viewsets in Tasks 2–7.
- `/implementing-mcp-tools` — before editing `tools.yaml` in Task 8.
- `/adopting-generated-api-types` — before writing frontend API calls in Tasks 10–11.

---

## File Structure

**Backend — modified:**

- `products/live_debugger/backend/models.py` — append `LiveDebuggerSession`, `LiveDebuggerSessionEntry`; add `session` FK to `LiveDebuggerProgram` (string reference, since `Session` is defined later in the file).
- `products/live_debugger/backend/api.py` — append session serializers + `LiveDebuggerSessionViewSet` with `@action` methods for `close`, `add_entry`, `install_program`, `uninstall_program`, `program_events`.
- `products/live_debugger/backend/test_api.py` — append `TestLiveDebuggerSessionAPI` class.
- `products/live_debugger/mcp/tools.yaml` — disable old `live-debugger-programs-*` tool entries; add new `debugging-session-*` entries.
- `products/live_debugger/manifest.tsx` — register two new scenes + routes + URL builders.
- `posthog/api/__init__.py` — register `LiveDebuggerSessionViewSet` on `projects_router`.

**Backend — created:**

- `products/live_debugger/backend/migrations/0003_debugging_session.py` — generated.

**Frontend — created:**

- `products/live_debugger/frontend/DebuggingSessions.tsx` — list scene.
- `products/live_debugger/frontend/DebuggingSession.tsx` — detail / notebook scene.
- `products/live_debugger/frontend/debuggingSessionsLogic.ts` — Kea logic for list.
- `products/live_debugger/frontend/debuggingSessionLogic.ts` — Kea logic for detail.

**Skill — modified:**

- `.agents/skills/instrumenting-with-hogtrace/SKILL.md` — rewrite around session workflow.

**Note on URL prefix:** existing live_debugger viewsets are registered on `projects_router`, so the actual URL is `/api/projects/{project_id}/live_debugger_sessions/...` (not `/api/environments/...` as the spec mentions — follow the existing pattern).

---

## Task 1: Models + migration

**Files:**

- Modify: `products/live_debugger/backend/models.py`
- Create: `products/live_debugger/backend/migrations/0003_debugging_session.py` (via `makemigrations`)
- Modify: `products/live_debugger/backend/migrations/max_migration.txt`

- [ ] **Step 1: Invoke the `/django-migrations` skill**

This is a mandatory project rule before any migration work.

- [ ] **Step 2: Append model classes and the new FK to `models.py`**

In `products/live_debugger/backend/models.py`, add the `session` FK on `LiveDebuggerProgram` (use a string reference so we don't have to reorder the file). Locate the existing `class LiveDebuggerProgram(UUIDModel):` and add the field next to `team`:

```python
class LiveDebuggerProgram(UUIDModel):
    class Status(models.TextChoices):
        INSTALLED = "installed", "Installed"
        UNINSTALLED = "uninstalled", "Uninstalled"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    session = models.ForeignKey(
        "live_debugger.LiveDebuggerSession",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="programs",
    )
    code = models.TextField()
    # ... rest of fields unchanged ...
```

Then at the end of the file (after `LiveDebuggerBreakpoint`), append:

```python
class LiveDebuggerSession(UUIDModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    title = models.TextField()
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "posthog_livedebuggersession"
        managed = True
        indexes = [
            models.Index(fields=["team_id", "status"], name="live_debug_sess_team_st_idx"),
        ]

    def __str__(self) -> str:
        return f"Session {self.pk} ({self.status}) for team {self.team_id}"


class LiveDebuggerSessionEntry(UUIDModel):
    class Kind(models.TextChoices):
        NOTE = "note", "Note"
        PROGRAM_INSTALL = "program_install", "Program install"
        PROGRAM_UNINSTALL = "program_uninstall", "Program uninstall"
        EVENT_HIGHLIGHT = "event_highlight", "Event highlight"
        CONCLUSION = "conclusion", "Conclusion"

    session = models.ForeignKey(LiveDebuggerSession, on_delete=models.CASCADE, related_name="entries")
    kind = models.CharField(max_length=32, choices=Kind.choices)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_livedebuggersessionentry"
        managed = True
        indexes = [
            models.Index(fields=["session_id", "created_at"], name="live_debug_entry_sess_ts_idx"),
        ]

    def __str__(self) -> str:
        return f"Entry {self.pk} ({self.kind}) in session {self.session_id}"
```

- [ ] **Step 3: Generate the migration**

Run from repo root:

```bash
hogli manage:py makemigrations live_debugger --name debugging_session
```

Expected: a new `0003_debugging_session.py` file is created in `products/live_debugger/backend/migrations/` containing `CreateModel` for `LiveDebuggerSession` and `LiveDebuggerSessionEntry`, plus `AddField` for `LiveDebuggerProgram.session`.

- [ ] **Step 4: Update `max_migration.txt`**

Overwrite `products/live_debugger/backend/migrations/max_migration.txt` with:

```text
0003_debugging_session
```

- [ ] **Step 5: Apply the migration**

```bash
hogli manage:py migrate live_debugger
```

Expected: `Applying live_debugger.0003_debugging_session... OK`.

- [ ] **Step 6: Smoke-import the models**

```bash
hogli manage:py shell -c "from products.live_debugger.backend.models import LiveDebuggerSession, LiveDebuggerSessionEntry; print(LiveDebuggerSession._meta.db_table, LiveDebuggerSessionEntry._meta.db_table)"
```

Expected output:

```text
posthog_livedebuggersession posthog_livedebuggersessionentry
```

- [ ] **Step 7: Commit**

```bash
git add products/live_debugger/backend/models.py products/live_debugger/backend/migrations/0003_debugging_session.py products/live_debugger/backend/migrations/max_migration.txt
git commit -m "feat(live_debugger): add debugging session models"
```

---

## Task 2: Session create/list/retrieve viewset + URL wiring

**Files:**

- Modify: `products/live_debugger/backend/api.py`
- Modify: `products/live_debugger/backend/test_api.py`
- Modify: `posthog/api/__init__.py`

- [ ] **Step 1: Invoke the `/improving-drf-endpoints` skill**

Mandatory project rule for any serializer/viewset change.

- [ ] **Step 2: Write the failing tests**

Append to `products/live_debugger/backend/test_api.py`:

```python
class TestLiveDebuggerSessionAPI(APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/live_debugger_sessions/{suffix}"

    def test_create_session(self):
        response = self.client.post(
            self._url(),
            data={"title": "Why is X failing?", "description": "Investigating X."},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.json()
        self.assertEqual(body["title"], "Why is X failing?")
        self.assertEqual(body["description"], "Investigating X.")
        self.assertEqual(body["status"], "open")
        self.assertIsNone(body["closed_at"])
        self.assertEqual(body["entries"], [])

    def test_list_sessions_most_recent_first(self):
        self.client.post(self._url(), data={"title": "First", "description": ""})
        self.client.post(self._url(), data={"title": "Second", "description": ""})
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = [s["title"] for s in response.json()["results"]]
        self.assertEqual(titles[:2], ["Second", "First"])

    def test_retrieve_session_includes_entries(self):
        create = self.client.post(self._url(), data={"title": "T", "description": ""})
        session_id = create.json()["id"]
        response = self.client.get(self._url(f"{session_id}/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["entries"], [])

    def test_team_isolation_on_retrieve(self):
        from posthog.models import Organization
        other_org = Organization.objects.create(name="Other org")
        other_team = Team.objects.create(organization=other_org, name="Other team")
        from products.live_debugger.backend.models import LiveDebuggerSession
        their_session = LiveDebuggerSession.objects.create(team=other_team, title="Theirs", description="")
        response = self.client.get(self._url(f"{their_session.id}/"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
```

- [ ] **Step 3: Run the tests and verify they fail**

```bash
hogli test products/live_debugger/backend/test_api.py::TestLiveDebuggerSessionAPI
```

Expected: 404 on POST routes — viewset isn't registered yet.

- [ ] **Step 4: Add serializers and viewset to `api.py`**

At the top of `products/live_debugger/backend/api.py`, ensure these imports exist (add if missing):

```python
from django.db import transaction
from django.utils import timezone
from rest_framework import status
```

Add this import alongside the existing model import:

```python
from products.live_debugger.backend.models import (
    LiveDebuggerBreakpoint,
    LiveDebuggerProgram,
    LiveDebuggerSession,
    LiveDebuggerSessionEntry,
)
```

Append to the end of the file:

```python
class LiveDebuggerSessionEntryListItemSerializer(serializers.ModelSerializer):
    """A single entry in a session's timeline."""

    class Meta:
        model = LiveDebuggerSessionEntry
        fields = ["id", "kind", "payload", "created_at"]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Unique identifier for the entry."},
            "kind": {
                "help_text": (
                    "Entry kind discriminator. One of: note, program_install, "
                    "program_uninstall, event_highlight, conclusion."
                ),
            },
            "payload": {
                "help_text": (
                    "Entry payload — shape depends on kind. "
                    "note/conclusion: {markdown: str}. "
                    "program_install/program_uninstall: {program_id: uuid}. "
                    "event_highlight: {event_uuids: list[str], caption: str}."
                ),
            },
            "created_at": {"help_text": "When the entry was appended."},
        }


class LiveDebuggerSessionSerializer(serializers.ModelSerializer):
    """Full session with its ordered entries timeline."""

    entries = LiveDebuggerSessionEntryListItemSerializer(many=True, read_only=True)

    class Meta:
        model = LiveDebuggerSession
        fields = ["id", "title", "description", "status", "created_at", "closed_at", "entries"]
        read_only_fields = ["id", "status", "created_at", "closed_at", "entries"]
        extra_kwargs = {
            "title": {"help_text": "Short human-readable name for the investigation."},
            "description": {"help_text": "What the agent is trying to figure out."},
            "status": {"help_text": "Lifecycle status: 'open' or 'closed'."},
            "created_at": {"help_text": "When the session was started."},
            "closed_at": {"help_text": "When the session was closed (null while open)."},
            "entries": {"help_text": "Ordered list of entries in this session, oldest first."},
        }

    def create(self, validated_data: dict) -> LiveDebuggerSession:
        validated_data["team"] = self.context["team"]
        return super().create(validated_data)


class LiveDebuggerSessionListItemSerializer(serializers.ModelSerializer):
    """Compact session for list views; omits entries."""

    class Meta:
        model = LiveDebuggerSession
        fields = ["id", "title", "description", "status", "created_at", "closed_at"]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Unique identifier for the session."},
            "title": {"help_text": "Short human-readable name for the investigation."},
            "description": {"help_text": "What the agent is trying to figure out."},
            "status": {"help_text": "Lifecycle status: 'open' or 'closed'."},
            "created_at": {"help_text": "When the session was started."},
            "closed_at": {"help_text": "When the session was closed (null while open)."},
        }


class LiveDebuggerSessionViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Start, list, inspect, and close debugging sessions.

    A session is the agent's investigation envelope. Every program install/uninstall,
    note, event highlight, and conclusion is appended to the session's timeline,
    producing a human-readable record of what the agent tried and what it learned.
    """

    scope_object = "live_debugger"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = ["create", "close", "add_entry", "install_program", "uninstall_program"]
    queryset = LiveDebuggerSession.objects.all()
    serializer_class = LiveDebuggerSessionSerializer
    basename = "live_debugger_sessions"
    http_method_names = ["get", "post", "head", "options"]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        from django.db.models import Prefetch
        return queryset.order_by("-created_at").prefetch_related(
            Prefetch("entries", queryset=LiveDebuggerSessionEntry.objects.order_by("created_at"))
        )

    def get_serializer_context(self) -> dict:
        context = super().get_serializer_context()
        context["team"] = self.team
        return context

    def get_serializer_class(self) -> type[serializers.Serializer]:
        if self.action == "list":
            return LiveDebuggerSessionListItemSerializer
        return LiveDebuggerSessionSerializer

    @extend_schema(
        summary="Start a debugging session",
        request=LiveDebuggerSessionSerializer,
        responses={
            201: OpenApiResponse(response=LiveDebuggerSessionSerializer, description="Session started."),
            400: OpenApiResponse(description="Invalid request body."),
        },
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        return super().create(request, *args, **kwargs)

    @extend_schema(
        summary="List debugging sessions",
        description="List sessions for the current project, most recently started first.",
        responses={200: OpenApiResponse(response=LiveDebuggerSessionListItemSerializer(many=True))},
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Show a debugging session",
        description="Retrieve a single session with its full ordered entries timeline.",
        responses={
            200: OpenApiResponse(response=LiveDebuggerSessionSerializer),
            404: OpenApiResponse(description="Session not found."),
        },
    )
    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        return super().retrieve(request, *args, **kwargs)
```

- [ ] **Step 5: Register the viewset's URL**

In `posthog/api/__init__.py`, immediately after the existing `live_debugger/programs` registration (around line 1136), add:

```python
projects_router.register(
    r"live_debugger_sessions",
    live_debugger.LiveDebuggerSessionViewSet,
    "project_live_debugger_sessions",
    ["project_id"],
)
```

- [ ] **Step 6: Run the tests and verify they pass**

```bash
hogli test products/live_debugger/backend/test_api.py::TestLiveDebuggerSessionAPI
```

Expected: 4 tests pass.

- [ ] **Step 7: Commit**

```bash
git add products/live_debugger/backend/api.py products/live_debugger/backend/test_api.py posthog/api/__init__.py
git commit -m "feat(live_debugger): add debugging session viewset (list/retrieve/create)"
```

---

## Task 3: Add-entry endpoint (note, event_highlight, conclusion)

**Files:**

- Modify: `products/live_debugger/backend/api.py`
- Modify: `products/live_debugger/backend/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to the `TestLiveDebuggerSessionAPI` class:

```python
    def _start_session(self) -> str:
        return self.client.post(self._url(), data={"title": "T", "description": ""}).json()["id"]

    def test_add_note_entry(self):
        sid = self._start_session()
        response = self.client.post(
            self._url(f"{sid}/entries/"),
            data={"kind": "note", "payload": {"markdown": "Trying probe X"}},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["kind"], "note")
        self.assertEqual(response.json()["payload"]["markdown"], "Trying probe X")

    def test_add_event_highlight_entry(self):
        sid = self._start_session()
        response = self.client.post(
            self._url(f"{sid}/entries/"),
            data={
                "kind": "event_highlight",
                "payload": {"event_uuids": ["00000000-0000-0000-0000-000000000001"], "caption": "look"},
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @parameterized.expand([
        ("note_missing_markdown", "note", {}),
        ("note_empty_markdown", "note", {"markdown": ""}),
        ("conclusion_missing_markdown", "conclusion", {}),
        ("highlight_missing_uuids", "event_highlight", {"caption": "c"}),
        ("highlight_empty_uuids", "event_highlight", {"event_uuids": [], "caption": "c"}),
        ("highlight_missing_caption", "event_highlight", {"event_uuids": ["00000000-0000-0000-0000-000000000001"]}),
    ])
    def test_add_entry_validation(self, _name, kind, payload):
        sid = self._start_session()
        response = self.client.post(
            self._url(f"{sid}/entries/"),
            data={"kind": kind, "payload": payload},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_add_entry_rejects_server_only_kinds(self):
        sid = self._start_session()
        for kind in ("program_install", "program_uninstall"):
            response = self.client.post(
                self._url(f"{sid}/entries/"),
                data={"kind": kind, "payload": {"program_id": "00000000-0000-0000-0000-000000000001"}},
                content_type="application/json",
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, msg=kind)

    def test_entries_appear_in_retrieve_oldest_first(self):
        sid = self._start_session()
        for n in range(3):
            self.client.post(
                self._url(f"{sid}/entries/"),
                data={"kind": "note", "payload": {"markdown": f"n{n}"}},
                content_type="application/json",
            )
        body = self.client.get(self._url(f"{sid}/")).json()
        self.assertEqual([e["payload"]["markdown"] for e in body["entries"]], ["n0", "n1", "n2"])
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
hogli test products/live_debugger/backend/test_api.py::TestLiveDebuggerSessionAPI
```

Expected: new tests 404 on `/entries/` path — endpoint not implemented.

- [ ] **Step 3: Add the request serializer and `add_entry` action**

In `api.py`, immediately above `class LiveDebuggerSessionViewSet`, add:

```python
class AddEntryRequestSerializer(serializers.Serializer):
    """Validates a direct-write session entry (note / event_highlight / conclusion).

    `program_install` and `program_uninstall` entries are server-written side effects
    of the install/uninstall endpoints and cannot be appended via this endpoint.
    """

    DIRECT_WRITE_KINDS = [
        LiveDebuggerSessionEntry.Kind.NOTE,
        LiveDebuggerSessionEntry.Kind.EVENT_HIGHLIGHT,
        LiveDebuggerSessionEntry.Kind.CONCLUSION,
    ]

    kind = serializers.ChoiceField(
        choices=DIRECT_WRITE_KINDS,
        help_text="Entry kind: note, event_highlight, or conclusion.",
    )
    payload = serializers.DictField(
        help_text=(
            "Payload shape depends on kind. "
            "note/conclusion: {markdown: str}. "
            "event_highlight: {event_uuids: list[str], caption: str}."
        ),
    )

    def validate(self, attrs: dict) -> dict:
        kind = attrs["kind"]
        payload = attrs["payload"]
        if kind in (
            LiveDebuggerSessionEntry.Kind.NOTE,
            LiveDebuggerSessionEntry.Kind.CONCLUSION,
        ):
            md = payload.get("markdown")
            if not isinstance(md, str) or not md:
                raise serializers.ValidationError({"payload": "markdown (non-empty string) is required."})
        elif kind == LiveDebuggerSessionEntry.Kind.EVENT_HIGHLIGHT:
            uuids = payload.get("event_uuids")
            caption = payload.get("caption")
            if not isinstance(uuids, list) or not uuids or not all(isinstance(u, str) for u in uuids):
                raise serializers.ValidationError({"payload": "event_uuids (non-empty list of strings) is required."})
            if not isinstance(caption, str):
                raise serializers.ValidationError({"payload": "caption (string) is required."})
        return attrs
```

Then inside `LiveDebuggerSessionViewSet`, add a private helper and the action:

```python
    def _ensure_open(self, session: LiveDebuggerSession) -> None:
        if session.status != LiveDebuggerSession.Status.OPEN:
            raise serializers.ValidationError("Session is closed; cannot mutate.")

    @extend_schema(
        summary="Append a note, event highlight, or conclusion entry",
        description=(
            "Appends a direct-write entry to the session's timeline. Use `kind` to "
            "select between `note`, `event_highlight`, and `conclusion`. `program_install` "
            "and `program_uninstall` entries are produced as side effects of the install/"
            "uninstall endpoints and cannot be added directly."
        ),
        request=AddEntryRequestSerializer,
        responses={
            201: OpenApiResponse(
                response=LiveDebuggerSessionEntryListItemSerializer,
                description="Entry appended.",
            ),
            400: OpenApiResponse(description="Invalid payload or session is closed."),
            404: OpenApiResponse(description="Session not found."),
        },
    )
    @action(methods=["POST"], detail=True, url_path="entries")
    def add_entry(self, request: Request, *args, **kwargs) -> Response:
        session = self.get_object()
        self._ensure_open(session)
        ser = AddEntryRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        entry = LiveDebuggerSessionEntry.objects.create(
            session=session,
            kind=ser.validated_data["kind"],
            payload=ser.validated_data["payload"],
        )
        return Response(
            LiveDebuggerSessionEntryListItemSerializer(entry).data,
            status=status.HTTP_201_CREATED,
        )
```

- [ ] **Step 4: Run the tests and verify they pass**

```bash
hogli test products/live_debugger/backend/test_api.py::TestLiveDebuggerSessionAPI
```

Expected: all `TestLiveDebuggerSessionAPI` tests pass.

- [ ] **Step 5: Commit**

```bash
git add products/live_debugger/backend/api.py products/live_debugger/backend/test_api.py
git commit -m "feat(live_debugger): add session entries endpoint with per-kind validation"
```

---

## Task 4: Install program in session

**Files:**

- Modify: `products/live_debugger/backend/api.py`
- Modify: `products/live_debugger/backend/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `TestLiveDebuggerSessionAPI`:

```python
    def test_install_program_creates_program_and_entry(self):
        sid = self._start_session()
        response = self.client.post(
            self._url(f"{sid}/install_program/"),
            data={"code": "probe foo {}", "description": "watching foo"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        program_id = response.json()["id"]
        self.assertEqual(response.json()["status"], "installed")

        body = self.client.get(self._url(f"{sid}/")).json()
        kinds = [e["kind"] for e in body["entries"]]
        self.assertIn("program_install", kinds)
        install_entry = next(e for e in body["entries"] if e["kind"] == "program_install")
        self.assertEqual(install_entry["payload"]["program_id"], program_id)

        # Program is linked back to the session
        from products.live_debugger.backend.models import LiveDebuggerProgram
        self.assertEqual(str(LiveDebuggerProgram.objects.get(id=program_id).session_id), sid)

    def test_install_program_rejected_when_session_closed(self):
        sid = self._start_session()
        self.client.post(self._url(f"{sid}/close/"), content_type="application/json")
        response = self.client.post(
            self._url(f"{sid}/install_program/"),
            data={"code": "probe foo {}", "description": ""},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
```

The second test depends on `close/` working — Task 6 implements it. Mark it `@unittest.skip` for now or accept it'll fail until Task 6:

```python
    @unittest.skip("Depends on Task 6: close endpoint")
    def test_install_program_rejected_when_session_closed(self):
        ...
```

Add `import unittest` at the top of `test_api.py` if missing.

- [ ] **Step 2: Run the tests and verify the new one fails**

```bash
hogli test products/live_debugger/backend/test_api.py::TestLiveDebuggerSessionAPI::test_install_program_creates_program_and_entry
```

Expected: 404 — `install_program` action not implemented.

- [ ] **Step 3: Add the install_program action**

In `api.py`, add this serializer above `LiveDebuggerSessionViewSet`:

```python
class InstallProgramInSessionRequestSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="The hogtrace program source code to install.")
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Human-readable description of what this program observes and why.",
    )
```

Inside `LiveDebuggerSessionViewSet`, add:

```python
    @extend_schema(
        summary="Install a hogtrace program inside a session",
        description=(
            "Atomically installs a hogtrace program scoped to this session and appends "
            "a `program_install` entry to the timeline. Returns the installed program."
        ),
        request=InstallProgramInSessionRequestSerializer,
        responses={
            201: OpenApiResponse(response=LiveDebuggerProgramSerializer, description="Program installed."),
            400: OpenApiResponse(description="Invalid payload or session is closed."),
            404: OpenApiResponse(description="Session not found."),
        },
    )
    @action(methods=["POST"], detail=True, url_path="install_program")
    def install_program(self, request: Request, *args, **kwargs) -> Response:
        session = self.get_object()
        self._ensure_open(session)
        ser = InstallProgramInSessionRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        with transaction.atomic():
            program = LiveDebuggerProgram.objects.create(
                team=self.team,
                session=session,
                code=ser.validated_data["code"],
                description=ser.validated_data.get("description", ""),
            )
            LiveDebuggerSessionEntry.objects.create(
                session=session,
                kind=LiveDebuggerSessionEntry.Kind.PROGRAM_INSTALL,
                payload={"program_id": str(program.id)},
            )
        return Response(
            LiveDebuggerProgramSerializer(program).data,
            status=status.HTTP_201_CREATED,
        )
```

- [ ] **Step 4: Run the tests and verify the new one passes**

```bash
hogli test products/live_debugger/backend/test_api.py::TestLiveDebuggerSessionAPI::test_install_program_creates_program_and_entry
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add products/live_debugger/backend/api.py products/live_debugger/backend/test_api.py
git commit -m "feat(live_debugger): install hogtrace programs inside a session"
```

---

## Task 5: Uninstall program in session

**Files:**

- Modify: `products/live_debugger/backend/api.py`
- Modify: `products/live_debugger/backend/test_api.py`

- [ ] **Step 1: Write the failing test**

Append to `TestLiveDebuggerSessionAPI`:

```python
    def test_uninstall_program_transitions_status_and_appends_entry(self):
        sid = self._start_session()
        install = self.client.post(
            self._url(f"{sid}/install_program/"),
            data={"code": "probe foo {}", "description": ""},
            content_type="application/json",
        )
        program_id = install.json()["id"]
        response = self.client.post(
            self._url(f"{sid}/uninstall_program/"),
            data={"program_id": program_id},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "uninstalled")

        body = self.client.get(self._url(f"{sid}/")).json()
        kinds = [e["kind"] for e in body["entries"]]
        self.assertEqual(kinds, ["program_install", "program_uninstall"])

    def test_uninstall_program_404_if_program_not_in_session(self):
        sid = self._start_session()
        response = self.client.post(
            self._url(f"{sid}/uninstall_program/"),
            data={"program_id": "00000000-0000-0000-0000-000000000001"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
hogli test products/live_debugger/backend/test_api.py::TestLiveDebuggerSessionAPI
```

Expected: the two new tests 404 on `uninstall_program/`.

- [ ] **Step 3: Add the uninstall_program action**

In `api.py`, add the request serializer above `LiveDebuggerSessionViewSet`:

```python
class UninstallProgramInSessionRequestSerializer(serializers.Serializer):
    program_id = serializers.UUIDField(help_text="ID of the program to uninstall.")
```

Inside `LiveDebuggerSessionViewSet`, add:

```python
    @extend_schema(
        summary="Uninstall a program from a session",
        description=(
            "Soft-uninstalls a program belonging to this session and appends a "
            "`program_uninstall` entry. Already-uninstalled programs are no-ops. "
            "Calling this on a program that does not belong to this session returns 404."
        ),
        request=UninstallProgramInSessionRequestSerializer,
        responses={
            200: OpenApiResponse(response=LiveDebuggerProgramSerializer, description="Program uninstalled."),
            400: OpenApiResponse(description="Invalid payload or session is closed."),
            404: OpenApiResponse(description="Program not found in session."),
        },
    )
    @action(methods=["POST"], detail=True, url_path="uninstall_program")
    def uninstall_program(self, request: Request, *args, **kwargs) -> Response:
        session = self.get_object()
        self._ensure_open(session)
        ser = UninstallProgramInSessionRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        program = LiveDebuggerProgram.objects.filter(
            id=ser.validated_data["program_id"],
            session=session,
            team=self.team,
        ).first()
        if program is None:
            return Response({"detail": "Program not found in session."}, status=status.HTTP_404_NOT_FOUND)
        with transaction.atomic():
            if program.status != LiveDebuggerProgram.Status.UNINSTALLED:
                program.status = LiveDebuggerProgram.Status.UNINSTALLED
                program.save(update_fields=["status", "updated_at"])
            LiveDebuggerSessionEntry.objects.create(
                session=session,
                kind=LiveDebuggerSessionEntry.Kind.PROGRAM_UNINSTALL,
                payload={"program_id": str(program.id)},
            )
        return Response(LiveDebuggerProgramSerializer(program).data)
```

- [ ] **Step 4: Run the tests and verify they pass**

```bash
hogli test products/live_debugger/backend/test_api.py::TestLiveDebuggerSessionAPI
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add products/live_debugger/backend/api.py products/live_debugger/backend/test_api.py
git commit -m "feat(live_debugger): uninstall programs inside a session"
```

---

## Task 6: Close session (auto-uninstall + optional conclusion)

**Files:**

- Modify: `products/live_debugger/backend/api.py`
- Modify: `products/live_debugger/backend/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `TestLiveDebuggerSessionAPI`:

```python
    def test_close_session_transitions_status(self):
        sid = self._start_session()
        response = self.client.post(self._url(f"{sid}/close/"), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "closed")
        self.assertIsNotNone(response.json()["closed_at"])

    def test_close_session_is_idempotent(self):
        sid = self._start_session()
        self.client.post(self._url(f"{sid}/close/"), content_type="application/json")
        response = self.client.post(self._url(f"{sid}/close/"), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "closed")

    def test_close_session_with_conclusion_appends_entry(self):
        sid = self._start_session()
        response = self.client.post(
            self._url(f"{sid}/close/"),
            data={"conclusion_markdown": "Root cause was X."},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        entries = response.json()["entries"]
        self.assertEqual(entries[-1]["kind"], "conclusion")
        self.assertEqual(entries[-1]["payload"]["markdown"], "Root cause was X.")

    def test_close_session_auto_uninstalls_installed_programs(self):
        sid = self._start_session()
        install = self.client.post(
            self._url(f"{sid}/install_program/"),
            data={"code": "probe foo {}", "description": ""},
            content_type="application/json",
        )
        program_id = install.json()["id"]
        self.client.post(self._url(f"{sid}/close/"), content_type="application/json")
        from products.live_debugger.backend.models import LiveDebuggerProgram
        self.assertEqual(LiveDebuggerProgram.objects.get(id=program_id).status, "uninstalled")

    def test_close_session_rejects_subsequent_entries(self):
        sid = self._start_session()
        self.client.post(self._url(f"{sid}/close/"), content_type="application/json")
        response = self.client.post(
            self._url(f"{sid}/entries/"),
            data={"kind": "note", "payload": {"markdown": "late note"}},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
hogli test products/live_debugger/backend/test_api.py::TestLiveDebuggerSessionAPI
```

Expected: the five new tests 404 on `close/`.

- [ ] **Step 3: Add the close action**

In `api.py`, add the request serializer above `LiveDebuggerSessionViewSet`:

```python
class CloseSessionRequestSerializer(serializers.Serializer):
    conclusion_markdown = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text=(
            "Optional markdown summary. If provided, a `conclusion` entry is appended "
            "before the session is closed."
        ),
    )
```

Inside `LiveDebuggerSessionViewSet`, add:

```python
    @extend_schema(
        summary="Close a debugging session",
        description=(
            "Atomically transitions the session to `closed`, sets `closed_at`, optionally "
            "appends a `conclusion` entry, and auto-uninstalls every program that still has "
            "`installed` status in this session. Idempotent: closing an already-closed "
            "session returns the session unchanged."
        ),
        request=CloseSessionRequestSerializer,
        responses={
            200: OpenApiResponse(response=LiveDebuggerSessionSerializer, description="Session closed."),
            400: OpenApiResponse(description="Invalid payload."),
            404: OpenApiResponse(description="Session not found."),
        },
    )
    @action(methods=["POST"], detail=True, url_path="close")
    def close(self, request: Request, *args, **kwargs) -> Response:
        session = self.get_object()
        if session.status == LiveDebuggerSession.Status.CLOSED:
            return Response(LiveDebuggerSessionSerializer(session).data)
        ser = CloseSessionRequestSerializer(data=request.data or {})
        ser.is_valid(raise_exception=True)
        conclusion = ser.validated_data.get("conclusion_markdown")
        with transaction.atomic():
            LiveDebuggerProgram.objects.filter(
                session=session,
                status=LiveDebuggerProgram.Status.INSTALLED,
            ).update(status=LiveDebuggerProgram.Status.UNINSTALLED)
            if conclusion:
                LiveDebuggerSessionEntry.objects.create(
                    session=session,
                    kind=LiveDebuggerSessionEntry.Kind.CONCLUSION,
                    payload={"markdown": conclusion},
                )
            session.status = LiveDebuggerSession.Status.CLOSED
            session.closed_at = timezone.now()
            session.save(update_fields=["status", "closed_at"])
        session.refresh_from_db()
        return Response(LiveDebuggerSessionSerializer(session).data)
```

- [ ] **Step 4: Un-skip the Task 4 closed-session rejection test**

Remove the `@unittest.skip` decorator from `test_install_program_rejected_when_session_closed`.

- [ ] **Step 5: Run the tests and verify they pass**

```bash
hogli test products/live_debugger/backend/test_api.py::TestLiveDebuggerSessionAPI
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add products/live_debugger/backend/api.py products/live_debugger/backend/test_api.py
git commit -m "feat(live_debugger): close session with auto-uninstall and optional conclusion"
```

---

## Task 7: Program events passthrough

**Files:**

- Modify: `products/live_debugger/backend/api.py`
- Modify: `products/live_debugger/backend/test_api.py`

- [ ] **Step 1: Write the failing test**

Append to `TestLiveDebuggerSessionAPI`:

```python
    def test_program_events_returns_empty_for_fresh_program(self):
        sid = self._start_session()
        install = self.client.post(
            self._url(f"{sid}/install_program/"),
            data={"code": "probe foo {}", "description": ""},
            content_type="application/json",
        )
        program_id = install.json()["id"]
        response = self.client.get(self._url(f"{sid}/program_events/?program_id={program_id}"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["results"], [])
        self.assertEqual(response.json()["count"], 0)

    def test_program_events_404_for_program_not_in_session(self):
        sid = self._start_session()
        response = self.client.get(
            self._url(f"{sid}/program_events/?program_id=00000000-0000-0000-0000-000000000001")
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_program_events_missing_program_id_400(self):
        sid = self._start_session()
        response = self.client.get(self._url(f"{sid}/program_events/"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
hogli test products/live_debugger/backend/test_api.py::TestLiveDebuggerSessionAPI
```

Expected: 404 — `program_events` not implemented.

- [ ] **Step 3: Add the program_events action**

Inside `LiveDebuggerSessionViewSet`, add:

```python
    @extend_schema(
        summary="Get probe events for a program in a session",
        description=(
            "Retrieves probe-hit events emitted by the given program. The program must "
            "belong to this session; otherwise 404 is returned. Returns events newest first."
        ),
        parameters=[
            OpenApiParameter(
                "program_id",
                OpenApiTypes.UUID,
                description="ID of the program (must belong to this session).",
                required=True,
            ),
            OpenApiParameter(
                "limit",
                OpenApiTypes.INT,
                description="Maximum number of events to return (default 100, max 1000).",
                required=False,
            ),
            OpenApiParameter(
                "offset",
                OpenApiTypes.INT,
                description="Pagination offset.",
                required=False,
            ),
        ],
        responses={
            200: OpenApiResponse(response=ProgramEventsResponseSerializer),
            400: OpenApiResponse(description="Missing program_id or invalid parameters."),
            404: OpenApiResponse(description="Program not found in session."),
        },
    )
    @action(methods=["GET"], detail=True, url_path="program_events")
    def program_events(self, request: Request, *args, **kwargs) -> Response:
        session = self.get_object()
        program_id = request.query_params.get("program_id")
        if not program_id:
            return Response({"detail": "program_id query param is required."}, status=status.HTTP_400_BAD_REQUEST)
        program = LiveDebuggerProgram.objects.filter(
            id=program_id,
            session=session,
            team=self.team,
        ).first()
        if program is None:
            return Response({"detail": "Program not found in session."}, status=status.HTTP_404_NOT_FOUND)
        param_serializer = ProgramEventsRequestSerializer(data=request.query_params)
        param_serializer.is_valid(raise_exception=True)
        params = param_serializer.validated_data
        tag_queries(product=Product.LIVE_DEBUGGER, feature=Feature.QUERY)
        events = LiveDebuggerProgram.get_program_events(
            team=self.team,
            program_id=str(program.id),
            limit=params["limit"],
            offset=params["offset"],
        )
        return Response(
            {
                "results": [event.to_json() for event in events],
                "count": len(events),
                "has_more": len(events) == params["limit"],
            }
        )
```

- [ ] **Step 4: Run the tests and verify they pass**

```bash
hogli test products/live_debugger/backend/test_api.py::TestLiveDebuggerSessionAPI
```

Expected: pass.

- [ ] **Step 5: Run the full live_debugger backend suite as a regression gate**

```bash
hogli test products/live_debugger/backend/
```

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add products/live_debugger/backend/api.py products/live_debugger/backend/test_api.py
git commit -m "feat(live_debugger): proxy program events through session viewset"
```

---

## Task 8: Regenerate OpenAPI + update MCP tools.yaml

**Files:**

- Modify: `products/live_debugger/mcp/tools.yaml`
- Auto-modified: `frontend/src/generated/core/api.*.ts`, `products/live_debugger/frontend/generated/api.*.ts`

- [ ] **Step 1: Invoke the `/implementing-mcp-tools` skill**

Mandatory project rule for any `tools.yaml` change.

- [ ] **Step 2: Regenerate the OpenAPI spec and frontend types**

```bash
hogli build:openapi
```

Expected: generated files under `frontend/src/generated/core/` and `products/live_debugger/frontend/generated/` are updated; the new session endpoints appear in `api.ts`.

- [ ] **Step 3: Identify the new operation IDs**

```bash
grep -E "live_debugger_sessions" products/live_debugger/frontend/generated/api.ts | head -30
```

Expected (operation IDs, exact names depend on drf-spectacular config — note the actual names you see):

```text
live_debugger_sessions_list
live_debugger_sessions_create
live_debugger_sessions_retrieve
live_debugger_sessions_add_entry_create
live_debugger_sessions_close_create
live_debugger_sessions_install_program_create
live_debugger_sessions_uninstall_program_create
live_debugger_sessions_program_events_retrieve
```

If any of the names differ, use what you actually see in the generated file for the `operation:` fields in the next step.

- [ ] **Step 4: Rewrite `products/live_debugger/mcp/tools.yaml`**

Replace the contents with:

```yaml
# MCP tool definition — tool entries are scaffolded from the OpenAPI schema.
# The tool list and operation IDs are kept in sync automatically:
#   pnpm --filter=@posthog/mcp run scaffold-yaml -- --sync-all
category: Live debugger
feature: live_debugger
url_prefix: /live-debugger
tools:
  debugging-session-start:
    operation: live_debugger_sessions_create
    enabled: true
    scopes:
      - live_debugger:write
    annotations:
      readOnly: false
      destructive: false
      idempotent: false
    title: Start a debugging session
    description: >
      Start a new debugging session — the envelope for an investigation. Provide a
      short `title` and a `description` of what you're trying to figure out. Returns
      the session including its id, which is required for every subsequent operation
      (install programs, add notes, highlight events, close).

  debugging-session-list:
    operation: live_debugger_sessions_list
    enabled: true
    mcp_version: 1
    scopes:
      - live_debugger:read
    annotations:
      readOnly: true
      destructive: false
      idempotent: true
    title: List debugging sessions
    description: >
      List debugging sessions for the current project, most recently started first.
      Returns each session's id, title, description, status, and timestamps.
      Timeline entries are omitted — use show to fetch them.
    list: true
    enrich_url: 'sessions/{id}'

  debugging-session-show:
    operation: live_debugger_sessions_retrieve
    enabled: true
    mcp_version: 1
    scopes:
      - live_debugger:read
    annotations:
      readOnly: true
      destructive: false
      idempotent: true
    title: Show a debugging session
    description: >
      Retrieve a single debugging session with its full ordered entries timeline.
      Use this to review what was tried, what was learned, and which events were
      highlighted in this investigation.
    enrich_url: 'sessions/{id}'

  debugging-session-close:
    operation: live_debugger_sessions_close_create
    enabled: true
    scopes:
      - live_debugger:write
    annotations:
      readOnly: false
      destructive: true
      idempotent: true
    title: Close a debugging session
    description: >
      Close the session. Atomically transitions status to `closed`, optionally
      appends a final `conclusion` entry (provide `conclusion_markdown`), and
      auto-uninstalls every program in this session that is still `installed`.
      Closed sessions reject further entries.

  debugging-session-add-entry:
    operation: live_debugger_sessions_add_entry_create
    enabled: true
    scopes:
      - live_debugger:write
    annotations:
      readOnly: false
      destructive: false
      idempotent: false
    title: Append entry to debugging session
    description: >
      Append a direct-write entry to the session's timeline. `kind` is one of:
      `note` (payload `{markdown}`), `event_highlight` (payload
      `{event_uuids: [uuid...], caption}`), or `conclusion` (payload `{markdown}`).
      Use `note` for hypotheses / reasoning / observations; `event_highlight` to
      pin informative events for the human reviewer with a group caption;
      `conclusion` for terminal summaries (typically supplied at close instead).

  debugging-session-install-program:
    operation: live_debugger_sessions_install_program_create
    enabled: true
    scopes:
      - live_debugger:write
    annotations:
      readOnly: false
      destructive: false
      idempotent: false
    title: Install hogtrace program in session
    description: >
      Atomically install a hogtrace program scoped to this session and append a
      `program_install` timeline entry. `code` is the hogtrace source;
      `description` should explain what this probe observes and why. Returns the
      installed program including its id (needed for uninstall and program-events).

  debugging-session-uninstall-program:
    operation: live_debugger_sessions_uninstall_program_create
    enabled: true
    scopes:
      - live_debugger:write
    annotations:
      readOnly: false
      destructive: true
      idempotent: true
    title: Uninstall program from session
    description: >
      Soft-uninstall a program belonging to this session and append a
      `program_uninstall` timeline entry. Calling this on an already-uninstalled
      program is a no-op; on a program not in the session it returns 404.

  debugging-session-program-events:
    operation: live_debugger_sessions_program_events_retrieve
    enabled: true
    scopes:
      - live_debugger:read
    annotations:
      readOnly: true
      destructive: false
      idempotent: true
    title: Get program events in a session
    description: >
      Retrieve probe-hit events emitted by a program scoped to this session.
      Returns events newest first, including captured local variables and stack
      trace. Use to inspect what the probe actually saw in production.

  # Old top-level program tools — disabled. Agents must use the session-scoped tools.
  live-debugger-programs-install:
    operation: live_debugger_programs_create
    enabled: false
  live-debugger-programs-uninstall:
    operation: live_debugger_programs_uninstall_create
    enabled: false
  live-debugger-programs-list:
    operation: live_debugger_programs_list
    enabled: false
  live-debugger-programs-show:
    operation: live_debugger_programs_retrieve
    enabled: false
  live-debugger-programs-events:
    operation: live_debugger_programs_events_retrieve
    enabled: false

  # Existing breakpoint endpoints — not exposed as MCP tools.
  live-debugger-breakpoints-active-retrieve:
    operation: live_debugger_breakpoints_active_retrieve
    enabled: false
  live-debugger-breakpoints-breakpoint-hits-retrieve:
    operation: live_debugger_breakpoints_breakpoint_hits_retrieve
    enabled: false
  live-debugger-breakpoints-create:
    operation: live_debugger_breakpoints_create
    enabled: false
  live-debugger-breakpoints-list:
    operation: live_debugger_breakpoints_list
    enabled: false
```

- [ ] **Step 5: Regenerate the MCP scaffold**

```bash
pnpm --filter=@posthog/mcp run scaffold-yaml -- --sync-all
```

Expected: the scaffold step succeeds. Any operation ID mismatch is reported here — fix the YAML against the actual generated operation names and rerun.

- [ ] **Step 6: Verify the MCP package compiles**

```bash
pnpm --filter=@posthog/mcp run typescript:check
```

Expected: no errors. If a tool handler references a request/response type that doesn't exist, the OpenAPI spec or the operation name is wrong — re-check Step 3's grep output.

- [ ] **Step 7: Commit**

```bash
git add products/live_debugger/mcp/tools.yaml frontend/src/generated/core/ products/live_debugger/frontend/generated/ services/mcp/
git commit -m "feat(live_debugger): scaffold MCP tools for debugging sessions"
```

(Adjust the staged paths to match what `git status` actually shows generated; `git add -A` would also work for this task but staged paths are clearer.)

---

## Task 9: Frontend manifest — register session scenes

**Files:**

- Modify: `products/live_debugger/manifest.tsx`

- [ ] **Step 1: Add new scenes, routes, and URL builders**

Replace the contents of `products/live_debugger/manifest.tsx` with:

```tsx
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
  name: 'Live Debugger',
  scenes: {
    LiveDebugger: {
      name: 'Live Debugger',
      import: () => import('./frontend/LiveDebugger'),
      projectBased: true,
    },
    DebuggingSessions: {
      name: 'Debugging Sessions',
      import: () => import('./frontend/DebuggingSessions'),
      projectBased: true,
    },
    DebuggingSession: {
      name: 'Debugging Session',
      import: () => import('./frontend/DebuggingSession'),
      projectBased: true,
    },
  },
  routes: {
    '/live-debugger': ['LiveDebugger', 'liveDebugger'],
    '/live-debugger/sessions': ['DebuggingSessions', 'debuggingSessions'],
    '/live-debugger/sessions/:id': ['DebuggingSession', 'debuggingSession'],
  },
  redirects: {},
  urls: {
    liveDebugger: (): string => '/live-debugger',
    debuggingSessions: (): string => '/live-debugger/sessions',
    debuggingSession: (id: string): string => `/live-debugger/sessions/${id}`,
  },
  fileSystemTypes: {
    live_debugger: {
      name: 'Live Debugger',
      iconType: 'live_debugger',
      href: () => urls.liveDebugger(),
      iconColor: ['var(--color-product-live-debugger-light)'],
      filterKey: 'live_debugger',
      flag: FEATURE_FLAGS.LIVE_DEBUGGER,
    },
  },
  treeItemsNew: [],
  treeItemsProducts: [
    {
      path: 'Live Debugger',
      intents: [ProductKey.LIVE_DEBUGGER],
      category: ProductItemCategory.UNRELEASED,
      type: 'live_debugger',
      href: urls.liveDebugger(),
      flag: FEATURE_FLAGS.LIVE_DEBUGGER,
      iconType: 'live_debugger',
      tags: ['alpha'],
      iconColor: ['var(--color-product-live-debugger-light)'] as FileSystemIconColor,
    },
  ],
}
```

- [ ] **Step 2: Type-check the frontend**

```bash
pnpm --filter=@posthog/frontend typescript:check
```

Expected: errors only about the not-yet-created `DebuggingSessions.tsx` / `DebuggingSession.tsx` imports. Those resolve in Tasks 10–11.

- [ ] **Step 3: Commit**

```bash
git add products/live_debugger/manifest.tsx
git commit -m "feat(live_debugger): register debugging session scenes in manifest"
```

---

## Task 10: Frontend — sessions list scene

**Files:**

- Create: `products/live_debugger/frontend/debuggingSessionsLogic.ts`
- Create: `products/live_debugger/frontend/DebuggingSessions.tsx`

- [ ] **Step 1: Invoke the `/adopting-generated-api-types` skill**

Mandatory before writing frontend API calls — use the generated functions from `products/live_debugger/frontend/generated/api.ts`.

- [ ] **Step 2: Create the Kea logic**

Create `products/live_debugger/frontend/debuggingSessionsLogic.ts`:

```typescript
import { actions, afterMount, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { liveDebuggerSessionsCreate, liveDebuggerSessionsList } from 'products/live_debugger/frontend/generated/api'
import type {
  PaginatedLiveDebuggerSessionListItemList,
  LiveDebuggerSessionListItem,
} from 'products/live_debugger/frontend/generated/api.schemas'

import type { debuggingSessionsLogicType } from './debuggingSessionsLogicType'

export const debuggingSessionsLogic = kea<debuggingSessionsLogicType>([
  path(['products', 'live_debugger', 'debuggingSessionsLogic']),

  actions({
    startSession: (title: string, description: string) => ({ title, description }),
  }),

  loaders(({ values }) => ({
    sessions: [
      [] as LiveDebuggerSessionListItem[],
      {
        loadSessions: async (): Promise<LiveDebuggerSessionListItem[]> => {
          const response: PaginatedLiveDebuggerSessionListItemList = await liveDebuggerSessionsList()
          return response.results ?? []
        },
        createSession: async ({ title, description }: { title: string; description: string }) => {
          const created = await liveDebuggerSessionsCreate({ title, description })
          // Refresh from the server so timestamps/ordering match the canonical list.
          return [{ ...created }, ...values.sessions]
        },
      },
    ],
  })),

  reducers({}),

  afterMount(({ actions }) => {
    actions.loadSessions()
  }),
])
```

Note: the imported types (`PaginatedLiveDebuggerSessionListItemList`, `LiveDebuggerSessionListItem`, function `liveDebuggerSessionsList`, `liveDebuggerSessionsCreate`) are generated by `hogli build:openapi` and live in `products/live_debugger/frontend/generated/`. If their names differ in the generated output, use what's actually there.

- [ ] **Step 3: Create the scene**

Create `products/live_debugger/frontend/DebuggingSessions.tsx`:

```tsx
import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { NotFound } from 'lib/components/NotFound'
import { Link } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { debuggingSessionsLogic } from './debuggingSessionsLogic'

export const scene: SceneExport = {
  component: DebuggingSessions,
  logic: debuggingSessionsLogic,
  productKey: ProductKey.LIVE_DEBUGGER,
}

export function DebuggingSessions(): JSX.Element {
  const isEnabled = useFeatureFlag('LIVE_DEBUGGER')
  const { sessions, sessionsLoading } = useValues(debuggingSessionsLogic)
  const { createSession } = useActions(debuggingSessionsLogic)

  if (!isEnabled) {
    return <NotFound object="Live debugger" caption="This feature is not enabled for your project." />
  }

  return (
    <>
      <SceneTitleSection
        name="Debugging sessions"
        description="Investigations the agent has run with hogtrace"
        resourceType={{ type: 'live_debugger' }}
      />

      <SceneContent>
        <div className="flex justify-end mb-2">
          <LemonButton
            type="primary"
            onClick={() => {
              const title = window.prompt('Session title')
              if (!title) {
                return
              }
              const description = window.prompt('What are you investigating?') ?? ''
              createSession({ title, description })
            }}
          >
            New session
          </LemonButton>
        </div>

        {sessionsLoading ? (
          <div className="text-muted">Loading…</div>
        ) : sessions.length === 0 ? (
          <div className="text-muted">No sessions yet.</div>
        ) : (
          <ul className="divide-y border rounded">
            {sessions.map((s) => (
              <li key={s.id} className="p-3 hover:bg-bg-light">
                <Link to={urls.debuggingSession(s.id)} className="block">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold">{s.title}</span>
                    <span className={s.status === 'open' ? 'text-xs text-success' : 'text-xs text-muted'}>
                      {s.status}
                    </span>
                  </div>
                  <div className="text-xs text-muted mt-0.5">
                    {dayjs(s.created_at).fromNow()}
                    {s.closed_at ? ` · closed ${dayjs(s.closed_at).fromNow()}` : ''}
                  </div>
                  {s.description && <div className="text-sm mt-1">{s.description}</div>}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </SceneContent>
    </>
  )
}

export default DebuggingSessions
```

- [ ] **Step 4: Type-check**

```bash
pnpm --filter=@posthog/frontend typescript:check
```

Expected: clean (or only the not-yet-implemented `DebuggingSession.tsx` import in `manifest.tsx`).

- [ ] **Step 5: Commit**

```bash
git add products/live_debugger/frontend/debuggingSessionsLogic.ts products/live_debugger/frontend/DebuggingSessions.tsx
git commit -m "feat(live_debugger): sessions list scene"
```

---

## Task 11: Frontend — session detail (notebook) scene

**Files:**

- Create: `products/live_debugger/frontend/debuggingSessionLogic.ts`
- Create: `products/live_debugger/frontend/DebuggingSession.tsx`

- [ ] **Step 1: Create the Kea logic**

Create `products/live_debugger/frontend/debuggingSessionLogic.ts`:

```typescript
import { actions, afterMount, kea, key, listeners, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import {
  liveDebuggerSessionsAddEntryCreate,
  liveDebuggerSessionsCloseCreate,
  liveDebuggerSessionsProgramEventsRetrieve,
  liveDebuggerSessionsRetrieve,
} from 'products/live_debugger/frontend/generated/api'
import type {
  LiveDebuggerSession,
  LiveDebuggerSessionEntryListItem,
  PaginatedProgramEventsResponse,
} from 'products/live_debugger/frontend/generated/api.schemas'

import type { debuggingSessionLogicType } from './debuggingSessionLogicType'

export interface SessionLogicProps {
  id: string
}

export const debuggingSessionLogic = kea<debuggingSessionLogicType>([
  props({} as SessionLogicProps),
  key((p) => p.id),
  path((k) => ['products', 'live_debugger', 'debuggingSessionLogic', k]),

  actions({
    closeSession: (conclusionMarkdown: string | null) => ({ conclusionMarkdown }),
    loadEventsForHighlight: (entryId: string, programId: string, uuids: string[]) => ({
      entryId,
      programId,
      uuids,
    }),
  }),

  loaders(({ props }) => ({
    session: [
      null as LiveDebuggerSession | null,
      {
        loadSession: async (): Promise<LiveDebuggerSession> => {
          return await liveDebuggerSessionsRetrieve(props.id)
        },
      },
    ],
    highlightedEvents: [
      {} as Record<string, PaginatedProgramEventsResponse['results']>,
      {
        loadEventsForHighlight: async ({ entryId, programId, uuids }) => {
          // Fetch all events for the program; UI filters down to the highlighted UUIDs.
          // Hackathon shortcut: no dedicated by-uuid endpoint.
          const response = await liveDebuggerSessionsProgramEventsRetrieve(props.id, {
            program_id: programId,
            limit: 1000,
          })
          const set = new Set(uuids)
          return {
            ...({} as Record<string, PaginatedProgramEventsResponse['results']>),
            [entryId]: (response.results ?? []).filter((e) => set.has(e.id)),
          }
        },
      },
    ],
  })),

  listeners(({ actions, props }) => ({
    closeSession: async ({ conclusionMarkdown }) => {
      await liveDebuggerSessionsCloseCreate(props.id, {
        conclusion_markdown: conclusionMarkdown ?? undefined,
      })
      actions.loadSession()
    },
  })),

  afterMount(({ actions }) => {
    actions.loadSession()
  }),
])
```

If the generated names for `liveDebuggerSessionsAddEntryCreate` / etc. differ, use the actual names from `products/live_debugger/frontend/generated/api.ts`. The import for `liveDebuggerSessionsAddEntryCreate` is left present because the UI scene below uses it.

- [ ] **Step 2: Create the scene**

Create `products/live_debugger/frontend/DebuggingSession.tsx`:

```tsx
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { debuggingSessionLogic } from './debuggingSessionLogic'
import type { LiveDebuggerSessionEntryListItem } from 'products/live_debugger/frontend/generated/api.schemas'

export const scene: SceneExport = {
  component: DebuggingSession,
  logic: debuggingSessionLogic,
  productKey: ProductKey.LIVE_DEBUGGER,
  paramsToProps: ({ params: { id } }) => ({ id }),
}

function NoteEntry({ entry }: { entry: LiveDebuggerSessionEntryListItem }): JSX.Element {
  const markdown = String(entry.payload?.markdown ?? '')
  return (
    <div className="border rounded p-3 bg-bg-light">
      <div className="text-xs text-muted mb-1">Note · {dayjs(entry.created_at).format('HH:mm:ss')}</div>
      <pre className="whitespace-pre-wrap text-sm font-sans">{markdown}</pre>
    </div>
  )
}

function ConclusionEntry({ entry }: { entry: LiveDebuggerSessionEntryListItem }): JSX.Element {
  const markdown = String(entry.payload?.markdown ?? '')
  return (
    <div className="border-2 border-success rounded p-3 bg-success-highlight">
      <div className="text-xs text-success font-semibold mb-1">
        Conclusion · {dayjs(entry.created_at).format('HH:mm:ss')}
      </div>
      <pre className="whitespace-pre-wrap text-sm font-sans">{markdown}</pre>
    </div>
  )
}

function ProgramInstallEntry({ entry }: { entry: LiveDebuggerSessionEntryListItem }): JSX.Element {
  const programId = String(entry.payload?.program_id ?? '')
  return (
    <div className="border rounded p-3 bg-bg-3000">
      <div className="text-xs text-muted mb-1">Program installed · {dayjs(entry.created_at).format('HH:mm:ss')}</div>
      <div className="font-mono text-xs">Program {programId}</div>
    </div>
  )
}

function ProgramUninstallEntry({ entry }: { entry: LiveDebuggerSessionEntryListItem }): JSX.Element {
  const programId = String(entry.payload?.program_id ?? '')
  return (
    <div className="text-xs text-muted px-3 py-1">
      Uninstalled program {programId} · {dayjs(entry.created_at).format('HH:mm:ss')}
    </div>
  )
}

function EventHighlightEntry({
  entry,
  sessionId,
}: {
  entry: LiveDebuggerSessionEntryListItem
  sessionId: string
}): JSX.Element {
  // Hackathon shortcut: render the caption + the raw UUID list. Full event payload
  // fetching is wired in the logic but not surfaced in the UI here.
  const uuids = (entry.payload?.event_uuids as string[]) ?? []
  const caption = String(entry.payload?.caption ?? '')
  return (
    <div className="border rounded p-3 bg-warning-highlight">
      <div className="text-xs text-muted mb-1">Event highlight · {dayjs(entry.created_at).format('HH:mm:ss')}</div>
      <div className="text-sm mb-1">{caption}</div>
      <ul className="text-xs font-mono">
        {uuids.map((u) => (
          <li key={u}>{u}</li>
        ))}
      </ul>
    </div>
  )
}

function Entry({ entry, sessionId }: { entry: LiveDebuggerSessionEntryListItem; sessionId: string }): JSX.Element {
  switch (entry.kind) {
    case 'note':
      return <NoteEntry entry={entry} />
    case 'conclusion':
      return <ConclusionEntry entry={entry} />
    case 'program_install':
      return <ProgramInstallEntry entry={entry} />
    case 'program_uninstall':
      return <ProgramUninstallEntry entry={entry} />
    case 'event_highlight':
      return <EventHighlightEntry entry={entry} sessionId={sessionId} />
    default:
      return <div className="text-xs text-muted">Unknown entry kind: {String(entry.kind)}</div>
  }
}

export function DebuggingSession(): JSX.Element {
  const isEnabled = useFeatureFlag('LIVE_DEBUGGER')
  const { session, sessionLoading } = useValues(debuggingSessionLogic)
  const { closeSession } = useActions(debuggingSessionLogic)

  if (!isEnabled) {
    return <NotFound object="Live debugger" caption="This feature is not enabled for your project." />
  }
  if (sessionLoading || !session) {
    return <div className="text-muted">Loading…</div>
  }

  return (
    <>
      <SceneTitleSection
        name={session.title}
        description={session.description || undefined}
        resourceType={{ type: 'live_debugger' }}
      />
      <SceneContent>
        <div className="flex items-center justify-between mb-3">
          <div className="text-xs text-muted">
            Status: <span className="font-semibold">{session.status}</span> · started{' '}
            {dayjs(session.created_at).fromNow()}
            {session.closed_at ? ` · closed ${dayjs(session.closed_at).fromNow()}` : ''}
          </div>
          {session.status === 'open' && (
            <LemonButton
              type="secondary"
              onClick={() => {
                const conclusion = window.prompt('Conclusion (optional)') || null
                closeSession(conclusion)
              }}
            >
              Close session
            </LemonButton>
          )}
        </div>
        <div className="space-y-2">
          {(session.entries ?? []).map((e) => (
            <Entry key={e.id} entry={e} sessionId={session.id} />
          ))}
          {(session.entries ?? []).length === 0 && <div className="text-muted text-sm">No entries yet.</div>}
        </div>
      </SceneContent>
    </>
  )
}

export default DebuggingSession
```

- [ ] **Step 3: Type-check**

```bash
pnpm --filter=@posthog/frontend typescript:check
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add products/live_debugger/frontend/debuggingSessionLogic.ts products/live_debugger/frontend/DebuggingSession.tsx
git commit -m "feat(live_debugger): session detail notebook scene"
```

---

## Task 12: Rewrite the hogtrace agent skill for the session workflow

**Files:**

- Modify: `.agents/skills/instrumenting-with-hogtrace/SKILL.md`

- [ ] **Step 1: Invoke the `/writing-skills` skill**

This is the standard project rule for skill edits.

- [ ] **Step 2: Rewrite `SKILL.md`**

Replace the contents of `.agents/skills/instrumenting-with-hogtrace/SKILL.md` with a session-first workflow. The new structure should keep the existing front-matter description but rewrite the body to teach this loop:

1. **Start a session** with `debugging-session-start` — short title + description of the goal.
2. **Install probes** with `debugging-session-install-program` — pass the hogtrace source. Each install is recorded on the session timeline.
3. **Read events** with `debugging-session-program-events` to see what the probe captured.
4. **Append a note** with `debugging-session-add-entry` (kind `note`) for the agent's reasoning, hypotheses, or what was just learned. Notes are how the human reading the notebook will follow the investigation.
5. **Pin informative events** with `debugging-session-add-entry` (kind `event_highlight`) — a list of event UUIDs plus a one-line caption explaining what they show.
6. **Refine**: install more programs, uninstall obsolete ones. Each is recorded.
7. **Close the session** with `debugging-session-close` and a `conclusion_markdown`. Closing auto-uninstalls remaining programs.

The rewrite must:

- Remove every reference to `live-debugger-programs-install` / `-uninstall` / `-list` / `-show` / `-events`. Those tools are now disabled.
- Stress that closing auto-uninstalls remaining programs (so the agent doesn't have to clean up manually, but also so the agent shouldn't close prematurely if it wants probes to keep firing).
- Preserve the existing references in `references/language.md`, `references/patterns.md`, `references/troubleshooting.md` — they describe the hogtrace language itself, which is unchanged. The skill body should still point readers at those.

Keep the file under 150 lines. The references already cover the language.

- [ ] **Step 3: Commit**

```bash
git add .agents/skills/instrumenting-with-hogtrace/SKILL.md
git commit -m "chore(live_debugger): rewrite hogtrace skill around debugging sessions"
```

---

## Task 13: End-to-end smoke test

**Files:** none (manual verification)

- [ ] **Step 1: Start the dev environment**

```bash
hogli up -d
hogli wait
```

Then open <http://localhost:8010/> in a browser and log in.

- [ ] **Step 2: Enable the `LIVE_DEBUGGER` feature flag for your user**

Either via the feature flags UI or via `hogli manage:py shell`. Confirm `/live-debugger` loads.

- [ ] **Step 3: Walk through the agent flow against the live API**

Using `curl` or the MCP inspector, exercise the full lifecycle:

```bash
PROJECT=1  # default project id
HOST=http://localhost:8010
COOKIE="$(< /tmp/posthog-session-cookie)"   # or use a Personal API Key via Authorization header

# Start
SID=$(curl -s -X POST "$HOST/api/projects/$PROJECT/live_debugger_sessions/" \
  -H "Content-Type: application/json" -b "$COOKIE" \
  -d '{"title":"smoke test","description":"E2E walk"}' | jq -r .id)
echo "session: $SID"

# Install
PID=$(curl -s -X POST "$HOST/api/projects/$PROJECT/live_debugger_sessions/$SID/install_program/" \
  -H "Content-Type: application/json" -b "$COOKIE" \
  -d '{"code":"probe foo {}","description":"smoke probe"}' | jq -r .id)
echo "program: $PID"

# Add a note
curl -s -X POST "$HOST/api/projects/$PROJECT/live_debugger_sessions/$SID/entries/" \
  -H "Content-Type: application/json" -b "$COOKIE" \
  -d '{"kind":"note","payload":{"markdown":"watching for X"}}'

# Highlight
curl -s -X POST "$HOST/api/projects/$PROJECT/live_debugger_sessions/$SID/entries/" \
  -H "Content-Type: application/json" -b "$COOKIE" \
  -d '{"kind":"event_highlight","payload":{"event_uuids":["00000000-0000-0000-0000-000000000001"],"caption":"check this"}}'

# Close with conclusion
curl -s -X POST "$HOST/api/projects/$PROJECT/live_debugger_sessions/$SID/close/" \
  -H "Content-Type: application/json" -b "$COOKIE" \
  -d '{"conclusion_markdown":"All good."}'

# Verify program auto-uninstalled
curl -s "$HOST/api/projects/$PROJECT/live_debugger_programs/$PID/" -b "$COOKIE" | jq .status
```

Expected: the final program status is `"uninstalled"`. The session's GET returns five entries in order: `program_install`, `note`, `event_highlight`, `conclusion`.

- [ ] **Step 4: Verify the UI**

In the browser:

1. Navigate to `/live-debugger/sessions`. The new session appears.
2. Click into it. The notebook shows: program_install card, note, event_highlight, conclusion.
3. Status shows `closed`. The "Close session" button is hidden.

- [ ] **Step 5: Document any deviations**

If anything diverges from the spec, note it in the PR description's `## 🤖 Agent context` block per `.github/pull_request_template.md`. Do not push fixes until the user reviews.

---

## Self-review (done by the planner)

**Spec coverage:** Every section of the spec maps to a task — models/migration (1), HTTP API (2–7), URL wiring (2 step 5), MCP surface (8), frontend manifest (9), list (10), detail/notebook (11), skill (12), end-to-end smoke (13). Testing requirements are inlined into each backend task (parameterized validation in Task 3, lifecycle in Task 6, team isolation in Task 2, passthrough in Task 7).

**Placeholder scan:** No "TBD" / "TODO" / "similar to" / unspecified-edge-case language. Generated operation IDs in Task 8 are explicitly flagged as guesses to verify against the regenerated `api.ts`.

**Type consistency:** `LiveDebuggerSession`, `LiveDebuggerSessionEntry`, `LiveDebuggerProgram.session` are used identically across model definitions (Task 1), serializers and viewset (Tasks 2–7), tools.yaml (Task 8), frontend types (Tasks 10–11). Action `url_path`s (`entries`, `close`, `install_program`, `uninstall_program`, `program_events`) match between viewset (Tasks 3–7), tools.yaml (Task 8), and frontend logic (Tasks 10–11).
