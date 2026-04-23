// Re-export @posthog/quill so TypeScript auto-import works with pnpm.
// Both `import { Button } from '@posthog/quill'` and
// `import { Button } from 'lib/ui/quill'` are valid.
export * from '@posthog/quill'
