/**
 * Barrel re-export of @posthog/quill for this app.
 *
 * Two reasons this exists:
 *   1. Gives consumers a stable `lib/ui/quill` alias (matching how the rest
 *      of this app imports local UI — `lib/ui/Button/...`, `lib/ui/Label`).
 *   2. Makes the TypeScript server in IDEs eagerly index @posthog/quill
 *      for auto-import suggestions. Without an in-tree import, some TS
 *      servers don't surface the package in Quick Fix "Add import"
 *      lists, even when `tsc --noEmit` resolves it fine.
 *
 * Consumers can import from either location — pick whichever matches the
 * surrounding file's conventions:
 *     import { Button, ButtonGroup } from 'lib/ui/quill'
 *     import { Button, ButtonGroup } from '@posthog/quill'
 */
export * from '@posthog/quill'
