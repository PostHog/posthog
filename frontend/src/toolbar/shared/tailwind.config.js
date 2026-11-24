// eslint-disable-next-line no-undef
const config = require('@posthog/tailwind/tailwind.config.js')

// The app's list scans every product and scene, which is slow. bin/check-toolbar-graph.mjs fails when
// the toolbar bundles a file outside this list.
// eslint-disable-next-line no-undef
module.exports = {
    ...config,
    content: [
        '../**/*.{ts,tsx}',
        '../../lib/**/*.{ts,tsx}',
        '../../scenes/product-tours/**/*.{ts,tsx}',
        '../../styles/**/*.{ts,tsx}',
        '../../taxonomy/**/*.{ts,tsx}',
        '../../types.ts',
        '../../generated/core/api.schemas.ts',
        '../../queries/nodes/WebVitals/definitions.ts',
        '../../../@posthog/lemon-ui/src/**/*.{ts,tsx}',
        '../../../../packages/quill/packages/quill/dist/**/*.{js,cjs}',
        '!../../**/*Type.ts',
    ],
}
