// The `@posthog/canvas-sdk` module a canvas imports: a facade over the `ph`
// bridge the runtime installs on the window before any canvas code runs, so
// canvases reaching for the `window.ph` global keep working.
//
// The desktop vendors this source into CANVAS_SDK_MODULE_SOURCE
// (products/desktop/packages/shared/src/canvas-platform.ts) to serve the same
// module in the edit preview. Change one, change the other.
export const ph = globalThis.ph
export default globalThis.ph

export function editable(name, props, params) {
    const schema = params || {}
    const values = {}
    for (const key of Object.keys(schema)) {
        if (props && props[key] !== undefined && typeof props[key] !== 'function') {
            values[key] = props[key]
        }
    }
    const attributes = {
        'data-ph-block': name,
        'data-ph-params': JSON.stringify(schema),
        'data-ph-props': JSON.stringify(values),
    }
    if (props && props['data-ph-src']) {
        attributes['data-ph-src'] = props['data-ph-src']
    }
    if (props && props.blockId) {
        attributes['data-ph-block-id'] = props.blockId
    }
    return attributes
}
