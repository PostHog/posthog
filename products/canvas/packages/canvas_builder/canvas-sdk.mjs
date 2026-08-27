// The `@posthog/canvas-sdk` module a canvas imports. It is a facade over the
// `ph` bridge the canvas runtime installs on the window before any canvas code
// runs, so canvases that use the `window.ph` global directly keep working.
//
// Both tiers resolve the bare specifier to this exact source: build.mjs inlines
// it into published bundles at build time, and the desktop's preview sandbox
// rewrites the import to a blob module built from its vendored copy
// (products/desktop/packages/shared/src/canvas-platform.ts). Change one, change
// the other. The typed surface lives in canvas-sdk.d.ts.
export const ph = globalThis.ph
export default globalThis.ph
