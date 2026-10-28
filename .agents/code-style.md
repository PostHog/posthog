# Code style

Each rule is tagged with what catches a violation, as in [architecture.md](architecture.md).
`[lint: <id>]` is machine-enforced. `[review]` is not.

## Python

- **Write as if mypy `--strict` were on.** `[review]` Annotate every signature, avoid `Any`, put type-only references under `TYPE_CHECKING`. The config is not fully strict yet; new code should be. When a change is type-risky run mypy the way CI does — `uv run mypy --cache-fine-grained .`, repo-wide, never a file subset. It follows imports, so a subset misses reverse-dependency breakage.
- **Imports stay at module level.** `[review]` ruff's `PLC0415` catches this, but `posthog/**`, `ee/**`, `common/**`, `tools/**` and most of `products/` are on grandfathered exemption lists, so CI does not block it in the trees you are most likely to be editing. Defer one only to break a true unavoidable circular import, to reference types under `TYPE_CHECKING`, or to keep a heavy or optional dependency off the import path. For the last case add a justified `# noqa: PLC0415 — keeps the heavy dep off the import path` on the line. Never blanket-suppress the rule.
- **A stdlib `@dataclass` must declare `frozen=` explicitly.** `[lint: prefer-frozen-dataclasses, test_dataclass_defaults.py]` A bare `@dataclass` fails the ratchet; `@dataclass(frozen=False)` passes it, so intentional mutability is a choice you state.
- **The house decorator is `@frozen` from `posthog.dataclasses`.** `[review]` Neither check prefers it over a declared stdlib `@dataclass`. Invoke `/writing-dataclasses` before adding or changing one, before returning or passing several values together, and before passing a dataclass through layers.
- **`product:lint` and the pytest collision test say where an `__init__.py` is required, and print the fix.** `[lint: product:lint, test_pytest_module_collisions.py]` Run them rather than reasoning about it.
- **Do not add or delete an `__init__.py` speculatively.** `[review]` Whether a directory needs one depends on what sits above it. Neither check objects to a needless one outside `products/` that creates no module-name collision, so only a reader catches that.
- Prefer classes over loose functions unless a class genuinely does not fit. `[review]` Use `pathlib` over `os.path`. Order functions and methods so a definition appears before its first call.

## Frontend

- **Follow [frontend/src/AGENTS.md](../frontend/src/AGENTS.md) for all frontend work** — the main app and `products/*/frontend/` alike, since they share components and generated types. `[review]` It covers reusing Lemon/quill components instead of hand-rolling tables, badges and labels, importing generated `*Api` types instead of handwriting them, and when to run typecheck and typegen.
- **TypeScript with explicit return types. Business logic goes in the kea logic file, not a React hook.** `[review]`
- **Guard every network-triggering button against double submission.** `[review]` Disable it and show a loading state (`loading` / `disabledReason` on `LemonButton`, or equivalent) while the request is in flight, and reset in both the success and error paths. Applies to `<form onSubmit>`, any `onClick` that calls `api.*`, and any kea `listener` that issues a request. Wire in the in-flight state from a loader `*Loading` selector, a reducer, or local `useState`.
- **Every surface must hold up narrow.** `[review]` The nav sidebar plus an open side panel leave a 1280px window about 520px of scene. Break on container queries, not `md:`/`lg:`/`xl:`. Wrap or truncate rather than clip, and stack halves that no longer fit. Render at a few widths before calling it done. We do not support mobile — no phone-width layouts, no touch-sized targets. See "Rule 6" in [frontend/src/AGENTS.md](../frontend/src/AGENTS.md).
- **quill is for MCP apps, the desktop app, and the web app UI behind the `today-rail-nav` feature flag; LemonUI is for the rest of the web app.** `[review]` `today-rail-nav` gates a quill redesign of the whole web app UI, built alongside the current UI and kept behind the flag for months. Build or change UI on that path with quill, and read [frontend/src/design.md](../frontend/src/design.md) first: it holds the components, tokens and decision rules. The current UI stays on LemonUI while the flag exists: do not add quill to it or convert it in place. On that flag-off path in `frontend/src/` and `products/*/frontend/` use LemonUI, including menus — `LemonMenu` with a `LemonButton` trigger. `lib/ui/DropdownMenu` (Radix) is legacy; do not add new ones. Where quill is right, do not mix the two inside one component, and remember quill uses Base UI's `render` prop, not Radix's `asChild`. Read [primitives/AGENTS.md](../packages/quill/packages/primitives/AGENTS.md) before importing quill — it covers component choice and spacing. Charts: [/working-with-charts](skills/working-with-charts/SKILL.md) for consumers, [charts/AGENTS.md](../packages/quill/packages/charts/AGENTS.md) for library changes. DataTable and DateTimePicker: [components/AGENTS.md](../packages/quill/packages/components/AGENTS.md).
- Use tailwind utility classes over inline styles, and `lib/dayjs` over a direct dayjs import. `[review]` oxlint warns on a `style` prop through `react/forbid-dom-props`, but a warning does not block.

## Comments

- **Explain _why_, not _what_,** and only where a future reader with no access to this PR or chat would otherwise be confused. `[review]` Default to one line. Python tests get no doc comments.
- **Never log change history or chat context in code.** `[review]` No "previously did X, now does Y", no "per <task/PR>", no "changed because…", no "AI:" or "agent:" notes. That belongs in the commit message and PR description.
- **When refactoring or moving code, keep the existing comments** unless the change actually makes them obsolete. `[review]`
- Use ASD-STE100 Simplified Technical English: active voice, simple tenses, one idea per sentence, consistent terms. `[review]`

## Tests

- **Every new test must catch a realistic regression no existing test catches.** `[review]` If you cannot name that regression, do not add the test. Assert observable behavior through the public interface, not implementation details, and keep it cheap — deterministic, isolated, at the lowest level that catches the bug. See `/writing-tests`.
- **Extend a relevant existing test rather than adding a standalone one** where practical, and parameterize variations of the same behavior (`parameterized` in Python, `test.each` in Jest). `[review]`
- Jest: one top-level `describe` per file. `[review]` Node.js Jest: `.test.ts` by default, `.serial.test.ts` only when shared mutable infrastructure cannot be isolated (a test that resets a shared database).

## Markdown and prose

- Semantic line breaks, no hard wrapping. American English spelling. `[review]`
