# Config-generic scanner suggestions: Phase 1b (frontend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the config-generic suggestions from Phase 1a visible in the Quality tab: render the suggestion's typed `changes[]` as per-kind change cards (prompt diff, tag add/remove/rename chips, flag/scale/length before to after) instead of the current prompt-only diff, for monitor and classifier scanners.

**Architecture:** A pure formatter (`describeConfigChange`) plus a thin presentational component (`ConfigChangeCards`) that reads `suggestion.changes`. The existing `SuggestionDetails` swaps its prompt-only diff for `ConfigChangeCards`, keeping the Monaco prompt diff for the `prompt`-kind change. Copy shifts from "prompt recommendation" to "recommendation". No kea-logic data-flow changes: the suggestion already arrives fully typed from Phase 1a, so this is presentation only.

**Tech Stack:** React + kea, TypeScript, LemonUI, Jest. Dir: `products/replay_vision/frontend/replay_scanners`.

## Global Constraints

- Feature stays behind the existing `replay-vision-quality` flag (the whole Quality tab already is).
- Backwards compatible: an old prompt-only suggestion (empty or absent `changes`, but with `base_prompt`/`suggested_prompt`) must still render a prompt diff. When `changes` is empty, fall back to the existing prompt-diff rendering so nothing regresses.
- Follow `frontend/src/AGENTS.md`: reuse Lemon components (LemonTag, LemonButton, etc.), import generated `*Api` types, put business logic in kea/pure helpers not React hooks, explicit return types.
- TypeScript required, explicit return types. Run `pnpm --filter=@posthog/frontend typescript:check` and the logic typegen before finishing.
- Comments minimal: explain why not what. NO em dashes and NO semicolons in comments (start a new sentence instead). This has been a recurring miss, double-check.
- User-facing copy: sentence case, plain language, no em dashes, no rule-of-three padding.
- Mandatory skills at the noted tasks: `/adopting-generated-api-types` (Task 1, consuming `ReplayScannerPromptSuggestionApi`), `/writing-tests` (Task 1 test).

## Test harness (authoritative)

- Jest logic/unit tests live beside the code (e.g. `scannerQualityLogic.test.ts`). Put the formatter test in `products/replay_vision/frontend/replay_scanners/components/configChanges.test.ts`.
- Run a frontend test: `pnpm --filter=@posthog/frontend jest <path>` (or `hogli test <path>`).
- Typecheck: `pnpm --filter=@posthog/frontend typescript:check`. If kea logic types are stale, run the frontend typegen first.
- The generated `ReplayScannerPromptSuggestionApi.changes` is typed `unknown` (a JSON field), so the frontend defines its own `ScannerConfigChange` interface to consume it. This is a JSON payload, not a serializer-typed field, so a handwritten interface is correct here and does not violate the generated-types rule.

---

## File structure

Create:

- `products/replay_vision/frontend/replay_scanners/components/configChanges.ts`: the `ScannerConfigChange` type and the pure `describeConfigChange(change)` formatter.
- `products/replay_vision/frontend/replay_scanners/components/ConfigChangeCards.tsx`: the presentational component rendering `changes[]`.
- `products/replay_vision/frontend/replay_scanners/components/configChanges.test.ts`: formatter unit tests.

Modify:

- `products/replay_vision/frontend/replay_scanners/components/ScannerQualityTab.tsx`: `SuggestionDetails` renders `ConfigChangeCards`; rename `PromptRecommendationPanel` to `ConfigRecommendationPanel`; update the "Prompt recommendation" copy.

---

## Task 1: The change model and formatter

**Files:**

- Create: `products/replay_vision/frontend/replay_scanners/components/configChanges.ts`
- Test: `products/replay_vision/frontend/replay_scanners/components/configChanges.test.ts`

**Interfaces:**

- Produces:
  - `export interface ScannerConfigChange { field: string; kind: 'prompt' | 'tags' | 'scale' | 'length' | 'flag'; op: 'set' | 'add' | 'remove' | 'rename'; before: unknown; after: unknown; rationale?: string }`
  - `export function parseConfigChanges(changes: unknown): ScannerConfigChange[]` (defensive: returns `[]` when not an array, filters entries missing `kind`/`op`).
  - `export function describeTagOp(change: ScannerConfigChange): { verb: 'Add' | 'Remove' | 'Rename'; text: string }` for the tag chips (e.g. rename gives `old -> new`).

- [ ] **Step 1: Write the failing test**

```ts
// configChanges.test.ts
import { describeTagOp, parseConfigChanges } from './configChanges'

describe('configChanges', () => {
  it('parses a well-formed change list and drops junk', () => {
    const parsed = parseConfigChanges([
      { field: 'tags', kind: 'tags', op: 'add', before: null, after: 'checkout', rationale: 'r' },
      { nope: true },
      'garbage',
    ])
    expect(parsed).toHaveLength(1)
    expect(parsed[0].kind).toBe('tags')
  })

  it('returns [] for non-array input', () => {
    expect(parseConfigChanges(undefined)).toEqual([])
    expect(parseConfigChanges({})).toEqual([])
  })

  it('describes tag ops', () => {
    expect(describeTagOp({ field: 'tags', kind: 'tags', op: 'add', before: null, after: 'a' }).verb).toBe('Add')
    expect(describeTagOp({ field: 'tags', kind: 'tags', op: 'remove', before: 'b', after: null }).verb).toBe('Remove')
    expect(describeTagOp({ field: 'tags', kind: 'tags', op: 'rename', before: 'b', after: 'c' }).text).toContain('b')
    expect(describeTagOp({ field: 'tags', kind: 'tags', op: 'rename', before: 'b', after: 'c' }).text).toContain('c')
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm --filter=@posthog/frontend jest products/replay_vision/frontend/replay_scanners/components/configChanges.test.ts`
Expected: FAIL, module not found.

- [ ] **Step 3: Write `configChanges.ts`**

```ts
export interface ScannerConfigChange {
  field: string
  kind: 'prompt' | 'tags' | 'scale' | 'length' | 'flag'
  op: 'set' | 'add' | 'remove' | 'rename'
  before: unknown
  after: unknown
  rationale?: string
}

const KINDS = new Set(['prompt', 'tags', 'scale', 'length', 'flag'])
const OPS = new Set(['set', 'add', 'remove', 'rename'])

export function parseConfigChanges(changes: unknown): ScannerConfigChange[] {
  if (!Array.isArray(changes)) {
    return []
  }
  return changes.filter(
    (c): c is ScannerConfigChange =>
      !!c && typeof c === 'object' && KINDS.has((c as any).kind) && OPS.has((c as any).op)
  )
}

export function describeTagOp(change: ScannerConfigChange): { verb: 'Add' | 'Remove' | 'Rename'; text: string } {
  if (change.op === 'rename') {
    return { verb: 'Rename', text: `${String(change.before)} → ${String(change.after)}` }
  }
  if (change.op === 'remove') {
    return { verb: 'Remove', text: String(change.before) }
  }
  return { verb: 'Add', text: String(change.after) }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pnpm --filter=@posthog/frontend jest products/replay_vision/frontend/replay_scanners/components/configChanges.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add products/replay_vision/frontend/replay_scanners/components/configChanges.ts \
        products/replay_vision/frontend/replay_scanners/components/configChanges.test.ts
git commit -m "feat(replay-vision): add config-change model and formatter for the quality tab"
```

---

## Task 2: The ConfigChangeCards component and wire-in

**Files:**

- Create: `products/replay_vision/frontend/replay_scanners/components/ConfigChangeCards.tsx`
- Modify: `products/replay_vision/frontend/replay_scanners/components/ScannerQualityTab.tsx`

**Interfaces:**

- Consumes: `ScannerConfigChange`, `parseConfigChanges`, `describeTagOp` from Task 1; the existing `SuggestionDiffPanes` (unchanged) for the `prompt`-kind card; `ReplayScannerPromptSuggestionApi`.
- Produces: `export function ConfigChangeCards({ suggestion, isDarkModeOn }: { suggestion: ReplayScannerPromptSuggestionApi; isDarkModeOn: boolean }): JSX.Element`.

Read `ScannerQualityTab.tsx` first (especially `SuggestionDiffPanes` around line 98, `SuggestionDetails` around line 155, and where `PromptRecommendationPanel` is defined and used). Reuse `SuggestionDiffPanes` for the prompt change so the Monaco diff behavior is unchanged.

Behavior of `ConfigChangeCards`:

- `const changes = parseConfigChanges(suggestion.changes)`.
- If `changes` has no `prompt`-kind entry but `suggestion.base_prompt`/`suggested_prompt` differ (an old row, or `changes` empty), render the existing prompt diff as a fallback so old suggestions never regress.
- Render one card per change, grouped by kind:
  - `prompt`: the existing `SuggestionDiffPanes` (labeled "Current prompt").
  - `tags`: a row of `LemonTag`s from `describeTagOp` (green for add, red/`danger` for remove, default for rename showing `old -> new`), under a "Tag changes" heading.
  - `flag`: a line `field: before to after` (e.g. "Allow inconclusive: off to on"), humanizing the field name and boolean.
  - `scale` / `length`: a line `field: before to after`. These will not appear until Phases 2/3 create scorer/summarizer proposers, but render them generically now so no follow-up is needed.
- Per-change `rationale` (when present) renders as small muted text under the card.

In `ScannerQualityTab.tsx`:

- In `SuggestionDetails`, replace the direct `SuggestionDiffPanes`/prompt-only block with `<ConfigChangeCards suggestion={suggestion} isDarkModeOn={isDarkModeOn} />`, keeping the top-level `rationale` block as-is (the suggestion-level rationale).
- Rename `PromptRecommendationPanel` to `ConfigRecommendationPanel` and update its references and the "Prompt recommendation" heading/copy to "Recommendation" (or "Suggested changes"). Keep the `data-attr`s stable where tests or the earlier verification relied on them (`vision-quality-*`), do not rename `data-attr` values.
- Update the fullscreen modal title "Prompt recommendation" to match the new copy.

- [ ] **Step 1: Write `ConfigChangeCards.tsx`**

Read the current `SuggestionDiffPanes` signature first and pass it exactly what it needs (`suggestion`, `beforeLabel`, `isDarkModeOn`, optional `onExpand`). Implement the component per the behavior above with explicit return type and no semicolons/em dashes in comments.

- [ ] **Step 2: Wire it into `SuggestionDetails` and rename the panel**

Make the edits above. Preserve all `data-attr` values.

- [ ] **Step 3: Typecheck and typegen**

Run: `pnpm --filter=@posthog/frontend typescript:check`
Expected: no new errors in `products/replay_vision`. If kea logic types are stale from any touched logic, run the frontend typegen and re-check. (This task touches no logic, so typegen is usually unnecessary.)

- [ ] **Step 4: Verify in the app (browser)**

The stack is running locally. As `test@posthog.com` (password `12345678`), open `http://localhost:8010/project/1/replay-vision/019f1e8f-bad9-730d-b850-c963eb94074b?tab=quality` and confirm the recommendation panel renders the prompt diff via the new change cards with no regression, and the copy reads "Recommendation". If Vite errors on a missing dep after a branch change, run `pnpm install` and restart the frontend unit. Capture a screenshot for the report.

- [ ] **Step 5: Run the quality-tab logic tests**

Run: `pnpm --filter=@posthog/frontend jest products/replay_vision/frontend/replay_scanners/scannerQualityLogic.test.ts products/replay_vision/frontend/replay_scanners/components/configChanges.test.ts`
Expected: PASS (no regression in the existing logic test).

- [ ] **Step 6: Commit**

```bash
git add products/replay_vision/frontend/replay_scanners/components/ConfigChangeCards.tsx \
        products/replay_vision/frontend/replay_scanners/components/ScannerQualityTab.tsx
git commit -m "feat(replay-vision): render config-generic change cards in the quality tab"
```

---

## Self-review checklist (after implementing)

- Spec coverage: change model + formatter (Task 1), change cards + panel rename + wire-in (Task 2). Full-config version history and scorer/summarizer preview evaluation are deferred (Phase 1c and Phases 2/3).
- Backwards compatibility: an old prompt-only suggestion (empty `changes`) still renders the prompt diff via the fallback. `data-attr` values unchanged.
- Placeholder scan: none. Type consistency: `ScannerConfigChange`, `parseConfigChanges`, `describeTagOp` names identical across Tasks 1 and 2.
- Copy: sentence case, no em dashes, no rule-of-three. Comments: minimal, no semicolons or em dashes.
