# Quill architecture review

Honest, senior-architect review of the quill packaging + distribution story,
written after the "split tokens CSS + colors.css entry point" change. Ordered
by impact, not by effort.

The high-level verdict: what's shipped today is a pragmatic improvement but
it perpetuates the architectural leaks that forced the `Code` consumer into
hand-rolled workarounds. Fixing those leaks is the path to an A-grade
design system package.

Use this file as a backlog. Check things off as they land.

---

## Bugs (do first, low effort, real breakage)

- [ ] **2. `theme-shape.css` has a hidden dependency on `color-system.css`**
      `--radius-*` is defined as `calc(var(--radius) - 4px)`. `--radius` only
      exists if the consumer has loaded `color-system.css`. Importing
      `theme-shape.css` on its own produces `calc(NaN)` for every radius
      utility with no error. Same hidden coupling exists for anything
      referencing `var(--accent)` etc.
      **Fix:** document the required import order loudly, OR move shared
      base variables (`--radius`, `--custom-variant dark`) into a dedicated
      `core.css` that every other file imports.

- [ ] **3. `@custom-variant dark` only lives in `theme-colors.css`**
      A consumer who imports `theme-typography.css` + `theme-shape.css`
      without `theme-colors.css` silently loses dark-mode variant support.
      Same fix as #2 — hoist the custom variant into a shared core file.

- [ ] **4. `ROOT_FONT_SIZE: 14 → 16` is a silent breaking change**
      The rem base flip was correct in isolation but I shipped it without
      verifying: - Does `apps/storybook` set `html { font-size: 14px }`? - Does `apps/web` (the main PostHog frontend) rely on the old values? - Do any stories visually regress in light + dark?

      **Fix:** audit every internal consumer, run Storybook in both themes,
      screenshot-diff the primitives stories, and only then keep the
      change. Bundle with a version bump + CHANGELOG entry.

- [ ] **5. No version bump for breaking changes**
      The session removed `./styles.css` from primitives exports, reshaped
      `tailwind-lib.css` from monolithic to `@import`-chained, and changed
      the rem base. All breaking. Even at `0.1.0-alpha.0` this warrants a
      bump (→ `0.2.0-alpha.0`) and a CHANGELOG note describing the
      migration path for early consumers.

---

## Architectural mistakes (the big DX wins)

- [x] **6. The `./colors.css` entry point is a lie and should be deleted** ✅
      Resolved as a no-op. The `./colors.css` entry only ever existed in a
      local experimental branch that was never merged to master, so there
      was nothing to delete. The underlying concern — a "colors-only" path
      that leaves primitive sizing broken — is structurally prevented by
      item #7 below, because pre-compiled CSS cannot collide with the
      consumer's Tailwind theme at all.

- [x] **7. Pre-compile Tailwind in the library build** ⭐ DONE
      A new `@posthog/quill` aggregate package at
      `packages/quill/packages/quill` owns the CSS pipeline. Its
      `src/index.css` is the Tailwind input (imports tokens,
      shadcn/tailwind.css, tw-animate-css, and `@source`s primitives /
      components / blocks source trees). A build step runs
      `@tailwindcss/cli` via `scripts/build-css.ts` to produce
      `dist/quill.css` — a flat, minified, pre-compiled stylesheet. The
      package exposes it as `./styles.css`. Consumers import the compiled
      output directly; their bundler treats it as plain CSS and does not
      need Tailwind. The Storybook app consumes exactly this path as the
      first-party smoke test and renders every primitive story correctly
      with zero `@source` directives pointing at quill sources.

- [x] **8. Decouple primitive sizing from the consumer's theme** ✅
      Subsumed by #7. Because primitives are pre-compiled against quill's
      own Tailwind theme at build time, the resulting `dist/quill.css`
      contains resolved selectors for every utility primitives reference
      (e.g. `.p-4 { padding: 16px }`) and the consumer's own Tailwind
      config never touches them. There is no way for the consumer's
      `--spacing-*`, `--text-*`, or `--radius-*` scale to override
      primitive sizing. The runtime theming knobs that remain are the
      CSS custom properties from `color-system.css` (`--primary`,
      `--background`, etc.) which consumers can override at `:root` if
      they want a recoloured build.

- [x] **9. Collapse to one published package: `@posthog/quill`** ✅
      Option B from the design discussion: a new
      `packages/quill/packages/quill` workspace member holds the public
      surface and re-exports primitives / components / blocks through a
      single `src/index.ts`. Consumers `import { Button } from
'@posthog/quill'`. The old `packages/quill/package.json` umbrella
      was renamed from `@posthog/quill` to `@posthog/quill-workspace`
      (private) so the name is free for the aggregate. The
      `@posthog/quill-primitives`, `@posthog/quill-components`, and
      `@posthog/quill-blocks` packages are now `private: true` workspace
      members that ship nowhere. `@posthog/quill-tokens` stays
      independently published for consumers who want programmatic
      access to the typed semantic-color exports. The publish workflow
      at `.github/workflows/publish-quill-npm.yml` was collapsed to
      publish only `@posthog/quill-tokens` and `@posthog/quill`.

- [x] **10. Drop `shadcn` as a peer dependency** ✅
      Removed from `@posthog/quill-primitives` peer dependencies and
      declared as a `devDependency` of the `@posthog/quill` aggregate
      instead. `shadcn/tailwind.css` is only a collection of
      `@custom-variant` definitions (`data-open`, `data-closed`,
      `data-checked`, etc.) plus keyframes — all compile-time macros. At
      library build time the Tailwind CLI expands them into concrete
      selectors that get baked into `dist/quill.css`. Consumers never
      see `@custom-variant` and do not need `shadcn` installed.

- [x] **11. Drop `tw-animate-css` as a peer dependency** ✅
      Same treatment as #10. `tw-animate-css` moved from
      `@posthog/quill-primitives` peer dependencies into the aggregate's
      `devDependencies`. Its utilities (`animate-in`, `fade-in`,
      `slide-in-from-*`, etc.) expand at build time and end up in the
      pre-compiled output. Zero runtime footprint for consumers.

- [x] **12. Stop shipping `src/` in the tarball** ✅
      `files` on `@posthog/quill-primitives`, `@posthog/quill-components`,
      and `@posthog/quill-blocks` dropped from `["src", "dist"]` to
      `["dist"]`. Those packages are now also `private: true` so they
      are never published anyway; the only package that goes to the
      registry is `@posthog/quill`, which was configured with
      `files: ["dist"]` from the start.

---

## Smaller DX + hygiene issues

- [x] **13. Declare `sideEffects` in every published package** ✅
      `@posthog/quill` declares `sideEffects: ["*.css"]` so bundlers
      preserve the compiled stylesheet import. The internal
      `@posthog/quill-primitives`, `@posthog/quill-components`, and
      `@posthog/quill-blocks` packages declare `sideEffects: false`
      (pure JS re-exports, no CSS side effects).

- [x] **14. Add `"./package.json": "./package.json"` to exports** ✅
      Added to `@posthog/quill`, `@posthog/quill-primitives`,
      `@posthog/quill-components`, and `@posthog/quill-blocks`.

- [ ] **15. Pin `tailwindcss` peer dep more tightly**
      `"tailwindcss": "^4.0.0"` accepts v4 betas which had different
      `@theme inline` semantics. Pin to `^4.1.0` or whatever the first
      stable release was that matches quill's current syntax.

- [x] **16. Add an `engines` field** ✅
      Added `"engines": { "node": ">=20" }` to the `@posthog/quill`
      aggregate (the only runtime-installable public package).

- [ ] **17. The README has five different ways to import CSS**
      `./index.css`, `./colors.css`, plus three granular `theme-*.css`
      entries. Great DS libraries have **one**. Every "here's another way"
      paragraph is a sign the library isn't opinionated enough yet. Once
      #6 and #7 land, this collapses to a two-line setup
      (`@import 'tailwindcss';` followed by `@import '@posthog/quill';`).
      **Fix:** rewrite the README around a single import story. Move
      granular controls to an "Advanced" section at the bottom.

---

## Tests and verification (from the previous conversation but still missing)

- [ ] **18. Contrast tests at the token level**
      Parameterized unit test that iterates known foreground/background
      pairs and asserts WCAG AA. Lives in `@posthog/quill-tokens`. Ten
      lines of test code, catches every "someone tweaked `--primary`"
      regression at the source before any component rebuilds.

- [ ] **19. Storybook + `@storybook/addon-a11y` axe-core in CI**
      Run via `@storybook/test-runner` against every story in both
      light and dark. Catches contrast regressions in composition, not
      just raw tokens.

- [ ] **20. Visual regression via Chromatic / Playwright screenshots**
      Cover every Button variant × state (default / hover / focus /
      disabled) × theme. Catches the "technically contrast-compliant but
      looks broken" class of bug.

- [ ] **21. Pack-and-install smoke test**
      Run `pnpm --filter @posthog/quill pack`, install the resulting
      tarball into a disposable temp app, and render `<Button />`. Hook
      it up in CI. Catches every `exports` resolution failure, missing
      `dist` file, missing peer dep, and "works in the monorepo but
      breaks on npm" bug. This is the single most valuable test for a
      library that ships to external consumers.

- [ ] **22. Acceptance test: the `Code` consumer's `quill.css` shrinks**
      Pick an absolute line count target for the consumer file after
      these changes. Without a target, there's no way to know whether
      the work actually solved the original problem.

---

## Process failures from this session (don't repeat)

- [ ] I ran `pnpm build` and declared success. For a CSS + theme change
      that's worse than no test — it gives a false sense of safety. Rule
      going forward: any CSS change must include a Storybook run in both
      themes before commit.

- [ ] I didn't check if `apps/storybook` or `apps/web` import the CSS files
      I was modifying. "Works in isolation, breaks in the monorepo" is a
      completely preventable class of bug. Always grep every consumer of a
      file before changing its contract.

- [ ] I removed `./styles.css` from primitives exports without a deprecation
      shim. At `0.1.0-alpha.0` it's defensible, but the habit is bad —
      leave a deprecated alias for one release and warn.

---

## Priority ordering

If tackling one at a time, recommended order:

1. **#2 + #3** (hidden coupling) — resolved incidentally by #7 landing;
   the split theme files never shipped on master and the pre-compiled
   pipeline now owns all `@import` chaining. Verify and close.
2. **#18** (token contrast tests) — 30 minutes, protects the whole palette.
3. **#21** (pack-and-install smoke test) — protects the new
   `@posthog/quill` aggregate against future regressions.
4. **#4 + #5** (rem base audit + version bump) — blocks a real release.
5. **#17** (README rewrite around a single import story) — now that
   there's only one public entry, the README should reflect it.
6. Everything else — hygiene, can be done opportunistically.

Grade after this branch: **B+**. The headline wins (#7 pre-compile, #9
single-package collapse, #10/#11/#12 peer-dep cleanup) are in. The
remaining gap to A is mostly testing infrastructure (#18, #21) and
documentation (#17).
