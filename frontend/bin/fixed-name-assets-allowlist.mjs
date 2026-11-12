// The .js, .mjs and .wasm files in frontend/dist/ that may keep a name without a content hash, relative to dist/.
// An entry that ends in `/` covers a whole directory: use one only where exact names change between builds.
export const FIXED_NAME_ASSET_GROUPS = [
    {
        reason:
            'posthog-js SDK bundles, copied by bin/copy-posthog-js. Customer sites and posthog-js itself load them ' +
            'from /static/<name>, so the fixed name is a public URL contract.',
        entries: [
            'array.full.es5.js',
            'array.full.js',
            'array.js',
            'conversations.js',
            'crisp-chat-integration.js',
            'customizations.full.js',
            'dead-clicks-autocapture.js',
            'exception-autocapture.js',
            'intercom-integration.js',
            'lazy-recorder.js',
            'logs.js',
            'posthog-recorder.js',
            'product-tours.js',
            'recorder-v2.js',
            'recorder.js',
            'surveys.js',
            'tracing-headers.js',
            'web-vitals-with-attribution.js',
            'web-vitals.js',
        ],
    },
    {
        reason:
            'Hashless copies of hashed entry points, written by createHashlessEntrypoints in ' +
            'common/esbuilder/utils.mjs as a load fallback. The app loads the hashed name.',
        entries: [
            'exporter.js',
            'exporterSharedChunkAnchors.js',
            'index.js',
            'infrastructure-admin.js',
            'render-query.js',
            'sharedChunkAnchors.js',
        ],
    },
    {
        reason:
            'Toolbar loader and app. posthog-js loads /static/toolbar.js on customer sites, so that name is a public ' +
            'URL contract. The loader (src/toolbar/floating/loader.ts) then loads toolbar-app.js by name with a ?t= cache buster.',
        entries: ['toolbar.js', 'toolbar/toolbar-app.js'],
    },
    {
        reason:
            'Staff admin console script, copied from public/admin-console/. The server-rendered page ' +
            'loads it with a ?v= version query (posthog/templates/admin_console/base.html), on each page load.',
        entries: ['admin-console/console.js'],
    },
    {
        reason:
            'DEBT: code the app loads at runtime by a fixed name, so a long-open tab can get a newer file than its JS. ' +
            'Each entry waits to be pinned to its content-hashed name. This group must shrink to zero; never add to it.',
        entries: [
            'decompressionWorker.js',
            'elkWorker.js',
            'hogqlParserWorker.js',
            'monacoEditorWorker.js',
            'monacoJsonWorker.js',
            'monacoTsWorker.js',
            'snappy_bg.wasm',
            'terminalWorker.js',
        ],
    },
]
