# Replay Vision: conversational, video-first scanner redesign

## Goal

Turn the single-shot `call_scanner_provider` Gemini call into a **multi-turn conversation over a context-cached video**, where:

- the **video is the primary input**, cached once and reused across turns;
- **analytics events are no longer dumped inline** — they're reachable only through a `get_events_around(rec_t, window)` tool the model calls when it needs context;
- **citations become timestamps** (`(t <sec>)`) instead of `(event_uuid <uuid>)`, so any video moment can be cited (not just ones with an event);
- the **Signals side mission is a second conversational step** after the core mission, so the model isn't juggling two opposed postures (summarize-from-events vs. find-what-events-miss) in one pass.

This addresses the two problems we diagnosed: (1) the core/side-mission attention conflict, and (2) the event-dump dominating the prompt and pulling the model off the video.

## Pivotal unknowns — de-risk first (Phase 0)

These shape the whole design; do not build before answering them with a throwaway spike against a **real cached session video**.

- **R1 — Tools + structured output coexistence.** Today we force JSON via `response_mime_type=application/json` + `response_json_schema`. Function calling is itself a structured-output mode; Gemini has historically not allowed forced `response_schema` _and_ `tools` in the same request. Verify on `google-genai==1.46.0` / Gemini 3. If they can't coexist, the fallback is the standard **tool-loop-then-constrain** pattern: run tool-calling turns with `tools` and _no_ schema (model freely calls tools or answers), then do one final constrained-decode turn with `response_schema` and _no_ tools to extract the structured object. This costs one extra call per mission but always works. Decide which pattern we're on — it changes the conversation driver.
- **R2 — Caching economics.** `caches.create` processes the video once; subsequent turns reference `cached_content` cheaply. Confirm the model's **minimum cacheable token count** (the video must exceed it) and set a **TTL** covering the conversation (a few minutes). For a 2-mission convo with a handful of tool calls, explicit caching should win, but measure vs. implicit caching — if the convo is only 2–3 turns the margin may be thin.
- **R3 — Token split.** Measure, on 3–5 real team-2 sessions, the video-token vs. events-token cost (pull a recording, count both). This tells us how much we actually save by moving events out, and whether caching is worth it.
- **De-risked already:** timestamp citations have **no alignment ambiguity** for their purpose — a citation seeks the player, and the player seek position _is_ `REC_T` (recording offset). We never need `recording_start + offset` for a citation (only the Signals' absolute-time fields needed that). So Phase 4 is safe.

Phase 0 deliverable: a go/no-go + the chosen structured-output pattern + token numbers. A few hours of scripting; gates the rest.

### Phase 0 results — RAN, all green → GO

Spiked against a real 170s team-2 recording on `google-genai==1.46.0` / `gemini-3-flash-preview`:

- **R1 (coexistence) — RESOLVED FAVORABLY.** `tools` + `response_json_schema` are accepted **in the same request** and return valid structured JSON. We do **not** need the tool-loop-then-constrain fallback; each mission turn can offer the events tool _and_ force its output schema. This is the big one.
- **R2 (caching) — WORKS.** `caches.create` with the video succeeded (~12k cached tokens); a follow-up `generate_content` with `cached_content` reused it (`cached_content_token_count` confirmed). Video served from cache across turns.
- **(b) function-call loop — WORKS.** The model watched the video, emitted `get_events_around({'rec_t': 30})`, accepted our `function_response`, and continued ("…a `$rageclick` at REC_T 31"). The driver loop is straightforward.
- **R3 (token split):** ~**12,071** video tokens for 170s (~71 tok/s; a long active session ≈ 30k+). A ~60-event inline blob ≈ **2,884** tokens — real sessions with hundreds–thousands of events run 5–15k+, i.e. comparable to or bigger than the video. So moving events to the tool is a real saving, and caching the ~12–32k-token video across ~4–6 turns clearly pays.
- **New implementation detail (Gemini 3 thinking model):** responses carry `thought_signature` parts. In the multi-turn tool loop you must append the model's **full `content`** (including thought signatures) back into `contents` — not a text reconstruction — or the model loses its reasoning chain across the tool round-trip. The spike's loop worked because it did exactly this.

Bottom line: the architecture is viable as specified; no fallback pattern required. Proceed to build.

## Build order (single PR)

This ships as **one PR**, gated behind a feature flag so it can merge without flipping the live scanner path (the existing single-shot flow stays the default until the eval clears, then we ramp the flag). The numbered items below are the build/commit order _within_ that PR, not separate PRs. Phase 0 is a throwaway pre-flight check (a REPL/script, not part of the PR) that settles the driver design before the code is written.

### Phase 1 — The events tool (pure, Redis-backed) — no behavior change

- Add `get_events_around(rec_t: int, window_s: int = 10) -> list[dict]`, a pure function that reads the already-fetched `ScannerLlmInputs` from Redis (the fetch step stashed it; the emit activity already reads it this way), filters the `EventTable` to the window around `rec_t`, and returns a compact, URL-resolved event list (apply `url_mapping`/`window_mapping` inside the tool so the model sees real URLs, not `url_1`).
- **The REC_T → events anchor is `recording` start, NOT session start — this is load-bearing.** `REC_T = 0` is the moment the _recording_ (first rrweb snapshot) begins. A recording can start well after the session does (delayed capture, sampling, a late `startSessionRecording()`), so the gap can be **minutes**. The correct anchor is `metadata.start_time` from `get_metadata`, which reads `session_replay_events.min_first_timestamp` = the recording/snapshot start. Do **not** anchor on anything session-derived (the `session_id` uuidv7 timestamp, an `events`-table min, etc.) — that would offset every lookup by the recording-start-minus-session-start delta and quietly return the wrong events.
- **Reuse the pipeline's existing recording-relative offsets, don't re-derive a second anchor.** `fetch_session_events._process_events` already computes event positions relative to `metadata.start_time` (the same value that feeds the current `(event_uuid)` citation `timestamp_ms`). Match `rec_t` against those existing offsets so the tool, the citations, and the footer all share one anchor and can't drift. (Confirm the exact basis when building — but the rule is: one recording-start anchor, used everywhere.)
- A `±window` query also absorbs the _small_ residual between `metadata.start_time` (CH snapshot-min) and the player's exact `REC_T=0` origin (`recordingSegments[0].startTimestamp`) — those differ by at most a buffer/meta-event or two. The window does **not** rescue a wrong _anchor_ (session vs recording), so the bullet above is the thing that matters; the window only covers sub-second-to-second jitter.
- Unit-test windowing/mapping/empty cases **and** a fixture where recording start ≠ session start, asserting the lookup keys off recording start.
- Rationale for Redis-backed: the events are already fetched once; the tool is an in-memory filter — no per-call ClickHouse query.

### Phase 2 — Conversation driver + video caching in `call_scanner_provider`

- Refactor the single `generate_content` + retry into a **bounded multi-turn loop**: create a video cache (`caches.create` with the video file + shared system instructions), then drive turns, executing any `function_call` by invoking the Phase-1 tool and appending the `function_response`, until the mission produces its structured output. Cap tool calls per mission (e.g. 6) and total turns.
- **Keep current behavior first** — single core mission, events still inline — to isolate the _refactor_ from the _behavior change_. Prove parity, then move on.
- Bump the activity `start_to_close_timeout` (currently 5 min) to cover multi-turn; keep the workflow-level wrap intact. Adapt the existing schema-validation retry to per-mission.
- Clean up the cache (delete or rely on TTL) and the uploaded video file as today.

### Phase 3 — Events tool-only (drop the inline dump)

- Remove the `<events>` / `<url_mapping>` / `<window_mapping>` blocks from `base.jinja`; register the `get_events_around` tool; instruct the model to call it when it needs event context (e.g. to confirm a `$rageclick`/`$exception` at a moment). Keep the small `<session_metadata>` block inline (cheap, useful).
- The core missions (monitor/classifier/scorer/summarizer) now get events via the tool. Watch friction_points / `$rageclick` grounding — these currently lean on inline events; verify the tool path preserves quality.

### Phase 4 — Timestamp citations replace event-uuid citations

- **Prompt:** swap the per-scanner citation instruction from `(event_uuid <uuid>)` to `(t <sec>)` (the `cite_in` macro + summarizer/monitor task text).
- **Backend:** `_resolve_citations` / `_extract_segments` / `_EVENT_UUID_CITATION_RE` parse `(t N)` → `timestamp_ms = N*1000`; drop/clamp citations outside `[0, recording_duration]` (the timestamp analogue of the uuid-existence check). `ChipSegment` drops `uuid`, keeps `timestamp_ms`. `event_timestamps` stops being needed for citation.
- **Frontend:** `ObservationCard.tsx` / `ReplayObservation.tsx` `Segment` type-guard drops the `uuid` requirement; the chip renders from `timestamp_ms` alone. **The seek path is unchanged** — `onSeek(timestampMs)` already exists.
- **Back-compat:** stored observations carry the old chip shape (`uuid` + `timestamp_ms`); make the frontend guard accept both (uuid optional) so historical observations still render.

### Phase 5 — Side mission as a second conversational step

- After the core mission's structured output, issue a **second turn**: "now the side mission" → the model returns the `signals` list (the multi-finding schema we already built this branch), reusing the **same cached video** + the events tool. No extra video processing.
- Remove the bolted-on `signals` field from the core response model (`_with_signals_field`); the side mission becomes its own structured output from turn 2. The downstream emit path (`ScannerCallOutput.signals` → emit activity → per-finding signals with `recording_*` anchor, `url`, integer `REC_T` offsets) is unchanged — only _how the model is asked_ moves from a field to a turn.

## Cross-cutting

- **Eval (the real arbiter):** A/B the same sessions through (a) today's bundled prompt and (b) the conversational video-first flow, scored on _fraction of signals that are genuinely video-only_ and core-mission quality (summary/verdict). Run before rollout.
- **Cost/latency:** monitor calls-per-observation and provider latency; the convo trades more calls for cheaper (cached) calls — confirm the net.
- **Rollout:** feature-flag the conversational path; run both in parallel on a sample, compare, then ramp. Keep the single-shot path until the eval clears.
- **Determinism/Temporal:** the whole convo stays inside the one `call_scanner_provider` activity (tool runs in-process over Redis); no new activities, no workflow-determinism concerns.

## Relationship to current work

This builds **on top of the current `tue/replay-vision-signal-quality` branch (PR #64708)** — not as a separate PR. The signal-quality work already there (signal enrichment, multi-finding `signals` list, `recording_*` metadata, integer `REC_T` offsets, `url`, the prompt levers) is the foundation this extends, and it all ships as one PR. The "side mission as turn 2" step reworks _how_ the side mission is invoked but reuses that branch's emit/schema machinery, so none of it is thrown away. Once the conversational scope is in, **update PR #64708's title and description** to reflect the broader change (it stops being just "ground signals in the recording" and becomes the conversational/video-first scanner redesign). A feature flag on the conversational path is still worth keeping so the (now large) PR can merge without flipping the live scanner until the eval clears — optional, but it's the cheap insurance for a change this size.
