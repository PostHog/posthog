// @posthog/quill-components
//
// Middle layer of the quill design system: higher-level compositions of
// primitives that wire several together with sensible defaults. Think
// FormField (Label + Input + error + description slot), ConfirmDialog
// (Dialog + destructive Button + focus management), ButtonGroup with
// dropdown menu chaining, DataTable wiring sort + filter + selection on
// top of Table primitives. Opinionated wrappers you'd otherwise hand-roll
// in every app.
//
// None of these are implemented yet. This file is an empty module so
// TypeScript treats it as one and downstream packages (the @posthog/quill
// aggregate in particular) can `export * from '@posthog/quill-components'`
// without hitting a "not a module" error while the layer is still empty.
// Each new component should be added here as a named export and will flow
// through to the public @posthog/quill surface automatically on the next
// build.

export {}
