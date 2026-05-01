// @posthog/quill-blocks
//
// Top layer of the quill design system: product-level patterns composed
// from components and primitives. Think PageHeader (title + breadcrumb +
// action slot), EmptyState (icon + copy + CTA), CommandPalette, the
// user-menu dropdown, a standard SettingsForm shell, and so on —
// opinionated shapes that stay consistent across every PostHog product
// surface.
//
// None of these are implemented yet. This file is an empty module so
// TypeScript treats it as one and downstream packages (the @posthog/quill
// aggregate in particular) can `export * from '@posthog/quill-blocks'`
// without hitting a "not a module" error while the layer is still empty.
// Each new block should be added here as a named export and will flow
// through to the public @posthog/quill surface automatically on the next
// build.

export {}
