// The `@posthog/canvas-sdk` module a canvas imports: a facade over the `ph`
// bridge the runtime installs on the window before any canvas code runs, so
// canvases reaching for the `window.ph` global keep working.
//
// The desktop vendors this source into CANVAS_SDK_MODULE_SOURCE
// (products/desktop/packages/shared/src/canvas-platform.ts) to serve the same
// module in the edit preview. Change one, change the other.
export const ph = globalThis.ph
export default globalThis.ph
