---
name: quill-code
description: Edit the @posthog/quill design system locally and consume the change in this repo (posthog-code) before it is published to npm. Use when changing quill components/primitives/tokens, when a quill change must be tested inside the Code app, or when the user mentions quill, the design system, the .local-quill tarball, or the @posthog/quill pnpm override.
---

# quill-code

`@posthog/quill` is **not** in this repo. It is a published catalog dependency whose
source lives in the main PostHog monorepo at `../posthog/packages/quill`. To test an
unpublished quill change inside this repo (posthog-code), you build quill, pack it to a
tarball, and point a pnpm `overrides` entry at that tarball. This is a **temporary
local-dev** state — revert before merging (see below).

## Quill layout (where to edit)

`../posthog/packages/quill` is the **workspace** (`@posthog/quill-workspace`). It
contains sub-packages, each a layer of the design system:

- `packages/primitives/src` — base components (Card, Badge, Button, Progress, …)
- `packages/components/src` — composed components (DataTable, DateTimePicker, Metric)
- `packages/blocks/src` — **product-level blocks** (e.g. `ExperimentCard`). Add the
  file here and export it from `packages/blocks/src/index.ts`.
- `packages/quill/src` — the **aggregate** that re-exports all layers as `@posthog/quill`.

A new export in any sub-package flows to `@posthog/quill` automatically on build.

## The loop (every quill change)

1. Edit/add the component in the right sub-package (above) and export it from that
   package's `src/index.ts`.
2. Re-sync into this repo manually — build → pack → point the override → reinstall:

   ```bash
   QUILL_DIR="${QUILL_DIR:-../posthog/packages/quill/packages/quill}"

   # a. Build the WHOLE quill workspace (two levels up from the aggregate), so the
   #    sub-packages rebuild BEFORE the aggregate bundles them.
   ( cd "$QUILL_DIR/../.." && pnpm build )

   # b. Pack into .local-quill/ under a UNIQUE filename. pnpm pins a tarball by
   #    integrity, so a stable name caches stale across re-syncs — drop old local
   #    tarballs first, then rename the packed file to a unique local name.
   rm -f .local-quill/posthog-quill-local-*.tgz
   ( cd "$QUILL_DIR" && npm pack --pack-destination "$(git rev-parse --show-toplevel)/.local-quill" )
   mv .local-quill/posthog-quill-[0-9]*.tgz ".local-quill/posthog-quill-local-$(git rev-parse --short HEAD)-$$.tgz"

   # c. Point the override at the new tarball, then reinstall.
   #    Edit pnpm-workspace.yaml so overrides['@posthog/quill'] = file:./.local-quill/<new file>
   pnpm install
   ```

   > Building only the aggregate (`packages/quill/packages/quill`) re-bundles the
   > sub-packages' **stale** `dist/`, so edits to primitives/components/blocks are
   > silently dropped. Always build at the workspace root.
3. Verify in the Code app (`pnpm dev`, or the `test-electron-app` skill). Repeat from 1.

After every quill edit you **must** re-run the sync — the app consumes the tarball, not
the quill source, so unsynced edits are invisible here.

If quill lives elsewhere, set `QUILL_DIR=/abs/path/to/posthog/packages/quill/packages/quill`.

## Why a tarball, not `link:`

`link:` symlinks into the mono's `node_modules` and drags in its **React 18** types,
colliding with this repo's **React 19** (dual-React → broken typecheck +
invalid-hook-call at runtime). The tarball is copied into this repo's store and deduped
against React 19. The filename is **content-hashed** because pnpm pins a tarball by
integrity, so a stable filename gets cached stale across re-syncs.

## The override (what the script rewrites)

In `pnpm-workspace.yaml`, under `overrides:`:

```yaml
'@posthog/quill': file:./.local-quill/posthog-quill-local-<hash>.tgz
```

There is also a permanent pin you should leave alone:

```yaml
'@posthog/quill>@base-ui/react': ^1.3.0   # quill ships a broken catalog: dep; do not remove
```

## Reverting (before merge)

The override is local-dev only. Once the quill change is published to npm:

1. Bump the catalog version in `pnpm-workspace.yaml` (`'@posthog/quill': 0.3.0-beta.x`)
   to the published version.
2. Restore the override line to point back at the catalog, or remove the `file:` override.
3. `pnpm install`.

Do not commit a `file:./.local-quill/...` override or the `.local-quill/` tarballs.
