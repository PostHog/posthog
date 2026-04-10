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

- [ ] **6. The `./colors.css` entry point is a lie and should be deleted**
      The README markets it as "use this when you have your own typography,
      spacing, radius, and shadow system." But quill primitives internally
      use `text-sm`, `p-4`, `rounded-md`, `shadow-sm` etc. — those utilities
      resolve against the **consumer's** `@theme`, not quill's. A consumer
      who follows the "colors-only" guidance gets primitives sized by their
      own spacing scale, with their own font scale and radius. Components
      look wrong and there's no clear error telling them why.

      **Fix:** revert the `./colors.css` export from primitives, components,
      and blocks. Better to have zero escape hatches than one that doesn't
      work. Replace with real solutions from #7 and #8 below.

- [ ] **7. Pre-compile Tailwind in the library build** ⭐ highest leverage
      Shipping `@source "./"` inside published CSS is a symptom, not a
      solution. It means: - Consumer must use Tailwind v4 (can't use quill with v3, vanilla
      CSS, CSS modules, Emotion, Stitches, Pigment, etc.) - Consumer's Tailwind must reach into `node_modules` on every build - Shipping `src/` in the tarball doubles package size - Tight coupling between quill's internal class usage and the
      consumer's build pipeline; Tailwind version skew can break
      scanning silently

      Radix Themes, Mantine, Park UI, Ark UI — **none** of them require
      consumers to scan their sources. They pre-compile.

      **Fix:** add a Tailwind CLI build step per package. Author components
      with Tailwind utilities as today, but at publish time resolve them
      against quill's own theme, emit a flat `dist/quill-primitives.css`,
      and make that the only CSS export. Consumers `@import` a static
      stylesheet and their Tailwind never touches quill at all. Works for
      non-Tailwind consumers too.

      This single change eliminates issues #2, #3, #6, #9 (src/ in tarball),
      and several points below. Ballpark: a day to get right.

- [ ] **8. Decouple primitive sizing from the consumer's theme**
      Related to #6 and #7. Even with pre-compilation, primitives reference
      token names like `--spacing-4`, `--text-sm`, `--radius-md` that can
      collide with the consumer's scale. Two acceptable models:

      - **(a) Quill owns the theme.** Accept that the library requires
        its full scale. Document it. Provide CSS variable knobs
        (`--quill-space-*`, `--quill-text-*`, etc.) for consumers to
        override individual values without replacing the whole scale.

      - **(b) Private namespace.** Components use `--quill-*` prefixed
        variables internally. Quill's theme seeds those from its own
        scale. Consumers can override individually without their app
        theme interfering.

      **Fix:** pick (a) or (b) and enforce it in the Tailwind config used
      for the library build.

- [ ] **9. Collapse to one published package: `@posthog/quill`** ⭐ DX win #2
      Today consumers juggle four package names: - `@posthog/quill-tokens` - `@posthog/quill-primitives` - `@posthog/quill-components` (currently empty) - `@posthog/quill-blocks` (currently empty)

      Plus a private `@posthog/quill` umbrella that publishes nothing.
      Every consumer must learn the layering, pick the right package, and
      keep four versions in lockstep. Radix Themes, Mantine core, Chakra,
      MUI — all ship one top-level entry.

      **Fix:** publish `@posthog/quill` as the primary package.
      Subpath exports for advanced users:
      ```
      import { Button } from '@posthog/quill'
      import { Block } from '@posthog/quill/blocks'
      import { tokens } from '@posthog/quill/tokens'
      ```
      Make `-primitives`, `-components`, `-blocks`, `-tokens` internal
      workspace packages that are not published individually. The publish
      workflow in `.github/workflows/publish-quill-npm.yml` collapses to
      publishing one package.

- [ ] **10. Drop `shadcn` as a peer dependency**
      Primitives currently declares `shadcn` as a peer dep because its
      `index.css` does `@import 'shadcn/tailwind.css'`. `shadcn` is a CLI
      tool, not a runtime package — this is a reverse dependency through a
      package whose primary purpose isn't to be imported. Consumers on npm
      will not expect a "design system CLI" to be a runtime requirement.

      **Fix:** vendor the handful of base resets that primitives actually
      needs into quill's own CSS. Delete the peer dep.

- [ ] **11. Vendor `tw-animate-css` (or at least drop the peer dep)**
      Same reasoning as #10. Quill uses a bounded set of animate utilities
      from `tw-animate-css`. Vendor them. Drop the peer dep. Installing
      `@posthog/quill` should give you a working library with zero extra
      manual installs.

- [ ] **12. Stop shipping `src/` in the tarball**
      `files: ["src", "dist"]` ships raw source, stories, and dev scaffolding
      to the registry. The only reason to ship `src/` today is `@source "./"`
      — and #7 deletes that reason. Once pre-compilation lands, `files` can
      drop to `["dist"]` and the tarball shrinks dramatically.

---

## Smaller DX + hygiene issues

- [ ] **13. Declare `sideEffects` in every published package**
      None of the four package.jsons have a `sideEffects` field. Bundlers
      can't safely tree-shake JS, and CSS imports need to be declared side
      effectful or they'll be dropped.
      **Fix:** `"sideEffects": ["*.css"]` on primitives/components/blocks.

- [ ] **14. Add `"./package.json": "./package.json"` to exports**
      Some tooling (TypeScript, bundler analyzers) reads the manifest via
      this subpath. Add it to all four packages.

- [ ] **15. Pin `tailwindcss` peer dep more tightly**
      `"tailwindcss": "^4.0.0"` accepts v4 betas which had different
      `@theme inline` semantics. Pin to `^4.1.0` or whatever the first
      stable release was that matches quill's current syntax.

- [ ] **16. Add an `engines` field**
      No Node pin anywhere. Add `"engines": { "node": ">=20" }` or
      whichever version the build actually requires.

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

1. **#2 + #3** (hidden coupling) — half an hour, unblocks safe file splits.
2. **#6** (delete the `colors.css` lie) — 15 minutes of deletion.
3. **#18** (token contrast tests) — 30 minutes, protects the whole palette.
4. **#7** (pre-compile Tailwind) — the big one, probably a day. Eliminates
   the root cause of most other issues on this list.
5. **#9** (collapse to one package) — half a day, massive DX improvement.
6. **#10 + #11** (vendor peer deps) — naturally falls out of #7.
7. **#21** (pack-and-install smoke test) — protects against future regressions.
8. **#4 + #5** (rem base audit + version bump) — blocks a real release.
9. Everything else — hygiene, can be done opportunistically.

Grade today: **B-** as a pragmatic improvement, **D** against "best DS
package ever." The gap between the two is almost entirely #7 + #9.
