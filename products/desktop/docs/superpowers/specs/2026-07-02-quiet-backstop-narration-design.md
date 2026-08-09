# Quiet backstop narration when viewing the task

Date: 2026-07-02
Status: approved

## Problem

Every permission request fires the deterministic speech backstop
(`speakDeterministic(taskRunId, session, "needs_input")` in
`packages/core/src/sessions/sessionService.ts`). `shouldSpeak` in
`packages/ui/src/features/notifications/speechRouting.ts` lets every
`needs_input` line bypass focus routing (`if (kind === "needs_input") return
true`), and the queue treats them as priority lines that are never coalesced.
Result: consecutive permission prompts each speak "needs your input" while the
user is already looking at the chat approving them.

## Design

Distinguish the two speakers sharing the speech pipe and gate them
differently:

- `source: "agent"` — lines from the agent's `speak` tool call. Keep current
  behavior: `needs_input` always plays; `done`/`progress` follow
  `spokenFocusMode`.
- `source: "backstop"` — deterministic lines ("finished", "needs your input")
  fired by turn-complete and permission events. Never play when the focus
  channel is `"suppress"` (app focused and the user is viewing that task).
  Otherwise follow `spokenFocusMode` as today.

`"suppress"` is per-task: a permission prompt on a task the user is *not*
viewing (app focused, different tab) still speaks — that is the multi-agent
case the voice exists for.

## Changes

1. `packages/ui/src/features/notifications/speechRouting.ts` — add
   `SpeechSource = "agent" | "backstop"`; `shouldSpeak(kind, source, channel,
   settings)`: backstop lines return `false` when `channel === "suppress"`;
   agent `needs_input` keeps its unconditional pass.
2. `packages/ui/src/features/notifications/speechNotifier.ts` — add `source`
   to `SpeakRequest`, pass through to `shouldSpeak`.
3. `packages/core/src/sessions/sessionService.ts` — add `source` to the
   `enqueueSpeech` dep signature; `speakDeterministic` sends `"backstop"`,
   the speak-tool handler sends `"agent"`.
4. `packages/ui/src/features/sessions/sessionServiceHost.ts` — type flows
   through unchanged (verify).
5. `packages/ui/src/features/notifications/speechRouting.test.ts` — cover the
   new matrix: backstop suppressed on `"suppress"`, backstop follows focus
   mode on `"toast"`/`"native"`, agent `needs_input` unaffected.

No settings UI change. No queue changes.

## Rejected alternatives

- Gate all `needs_input` by focus mode (no source flag): also mutes the
  agent's intentional "Hey Jon" lines.
- Debounce/dedupe backstop lines in the queue: treats the symptom; focus
  suppression already kills repeats once the user is present, and serial
  prompts while away should each speak.
