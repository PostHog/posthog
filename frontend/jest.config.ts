import type { Config } from 'jest'

process.env.TZ = process.env.TZ || 'UTC'

/*
 * For a detailed explanation regarding each configuration property and type check, visit:
 * https://jestjs.io/docs/en/configuration.html
 */

const esmModules = [
    'query-selector-shadow-dom',
    // @posthog/brand is ESM-only (ships .mjs); let Sucrase transpile it so its import/export parses.
    '@posthog/brand',
    // @shadcn/react ships ESM-only; @posthog/quill-primitives chat components re-export its
    // message-scroller, pulling it into frontend test module graphs via the quill barrel.
    '@shadcn/react',
    '@react-hook',
    '@medv',
    // @toon-format/toon ships ESM-only; the posthog_ai widget extractors decode TOON tool output.
    '@toon-format',
    'monaco-editor',
    '@posthog/hedgehog-mode',
    // @marsidev/react-turnstile ships ESM-only; the auth flow variant registry pulls it
    // into test module graphs (including Exporter via the shared login ERROR_MESSAGES export).
    '@marsidev/react-turnstile',
    'escape-string-regexp',
    '@tiptap',
    '@mathjax',
    'marked',
    'lowlight',
    'devlop',
    'zwitch',
    // posthog-js's rrweb subpath entries are shipped as ESM; the rest of posthog-js
    // is CJS, so we scope the transform to just dist/rrweb* to avoid retranspiling main.js.
    'posthog-js/dist/rrweb',
    // react-markdown and its ecosystem are all ESM-only
    'react-markdown',
    'remark-.*',
    'rehype-.*',
    'unified',
    'bail',
    'trough',
    'vfile',
    'vfile-message',
    'hast-util-.*',
    'mdast-util-.*',
    'unist-util-.*',
    'estree-util-.*',
    'micromark',
    'micromark-.*',
    'parse-entities',
    'character-entities.*',
    'character-reference-invalid',
    'is-plain-obj',
    'is-decimal',
    'is-hexadecimal',
    'is-alphabetical',
    'is-alphanumerical',
    'decode-named-character-reference',
    'trim-lines',
    'comma-separated-tokens',
    'space-separated-tokens',
    'property-information',
    'stringify-entities',
    'html-void-elements',
    'html-url-attributes',
    'ccount',
    'longest-streak',
    'markdown-table',
    '@mathjax/src',
    // MSW v2 and its dependencies ship ESM that resolves under the forced `default` export condition
    'msw',
    '@mswjs/.*',
    '@bundled-es-modules/.*',
    '@open-draft/.*',
    'rettime',
    'strict-event-emitter',
    'headers-polyfill',
    'outvariant',
    'until-async',
    'is-node-process',
    // yaml's browser entry (used under the jsdom env) is ESM and re-exports its CJS dist
    'yaml/browser',
]
function rootDirectories(): string[] {
    return [
        '<rootDir>/src',
        '<rootDir>/bin',
        '<rootDir>/../products',
        '<rootDir>/../packages/quill/packages/charts/src',
        '<rootDir>/../packages/quill/packages/components/src',
        '<rootDir>/../packages/llm-normalizer/src',
        '<rootDir>/../common/esbuilder',
    ]
}

const config: Config = {
    clearMocks: true,

    coverageDirectory: 'coverage',

    coverageProvider: 'v8',

    // Faking queueMicrotask starves the web-streams pump that MSW v2 response bodies ride on:
    // each pump microtask lands in the fake queue and respawns the next one, so any
    // advanceTimersByTimeAsync allocates unboundedly until the worker OOMs. Keep microtasks real.
    // setImmediate drives MSW v2's interceptor response pump the same way — faking it deadlocks
    // any test that awaits a mocked request under fake timers (upstream stance: mswjs/msw#1830).
    // Merged into per-test `jest.useFakeTimers({...})` configs unless they pass their own doNotFake.
    fakeTimers: {
        doNotFake: ['queueMicrotask', 'setImmediate'],
    },

    moduleNameMapper: {
        '^kea$': '<rootDir>/src/test/keaTestModule.js',
        '^.+\\.(css|less|scss|svg|png)$': '<rootDir>/src/test/mocks/styleMock.js',
        // @posthog/brand PNG subpaths resolve to .mjs modules that build a URL via
        // `new URL("./x.png", import.meta.url)` — import.meta is unavailable under Sucrase/CJS,
        // so mock them to the styleMock string instead of executing them.
        '^@posthog/brand/.*/png/.*$': '<rootDir>/src/test/mocks/styleMock.js',
        // devHmrStreamAbort subscribes to Vite HMR events via import.meta, which Sucrase passes
        // through into CJS and Jest then cannot compile ("Cannot use 'import.meta' outside a module").
        // It is dev-server-only behavior, so stub it out rather than transform it.
        devHmrStreamAbort$: '<rootDir>/src/test/mocks/emptyMock.js',
        '^.+\\.sql\\?raw$': '<rootDir>/src/test/mocks/rawFileMock.js',
        '^(.+)\\.yaml\\?raw$': '$1.yaml',
        '^(.+)\\.md\\?raw$': '$1.md',
        '^~/(.*)$': '<rootDir>/src/$1',
        '^@posthog/hogql-parser$': '<rootDir>/node_modules/@posthog/hogql-parser/dist/index.cjs',
        // @posthog/hogvm ships as ESM-only; map to the TS source so Jest (Sucrase) can handle it.
        // Required for sidePanelNotificationsLogic.test.ts and other tests with a transitive
        // import chain through src/lib/hog.ts.
        '^@posthog/hogvm$': '<rootDir>/node_modules/@posthog/hogvm/src/index.ts',
        '^@posthog/lemon-ui(|/.*)$': '<rootDir>/@posthog/lemon-ui/src/$1',
        '^lib/(.*)$': '<rootDir>/src/lib/$1',
        '^react-markdown$': '<rootDir>/src/test/mocks/reactMarkdownMock.js',
        '^remark-gfm$': '<rootDir>/src/test/mocks/emptyMock.js',
        '^remark-breaks$': '<rootDir>/src/test/mocks/emptyMock.js',
        '^mdast-util-find-and-replace$': '<rootDir>/src/test/mocks/emptyMock.js',
        '^chart\\.js$': '<rootDir>/src/test/insight-testing/chartjs-mock',
        'chartjs-plugin-crosshair': '<rootDir>/src/test/mocks/emptyMock.js',
        'chartjs-plugin-annotation': '<rootDir>/src/test/mocks/chartjsPluginMock.js',
        'chartjs-plugin-datalabels': '<rootDir>/src/test/mocks/chartjsPluginMock.js',
        'chartjs-plugin-stacked100': '<rootDir>/src/test/mocks/chartjsStacked100Mock.js',
        'chartjs-plugin-trendline': '<rootDir>/src/test/mocks/chartjsPluginMock.js',
        'chartjs-plugin-zoom': '<rootDir>/src/test/mocks/chartjsPluginMock.js',
        'chartjs-adapter-dayjs-3': '<rootDir>/src/test/mocks/emptyMock.js',
        torph: '<rootDir>/src/test/mocks/torphMock.js',
        'monaco-editor': '<rootDir>/node_modules/monaco-editor/esm/vs/editor/editor.api.d.ts',
        '^scenes/(.*)$': '<rootDir>/src/scenes/$1',
        '^products/(.*)$': '<rootDir>/../products/$1',
        '^common/(.*)$': '<rootDir>/../common/$1',
        '^@posthog/replay-shared$': '<rootDir>/../common/replay-shared/src/index.ts',
        '^@posthog/replay-shared/(.*)$': '<rootDir>/../common/replay-shared/src/$1',
        '^@posthog/llm-normalizer$': '<rootDir>/../packages/llm-normalizer/src/index.ts',
        '^@posthog/llm-normalizer/(.*)$': '<rootDir>/../packages/llm-normalizer/src/$1',
        '^@posthog/quill$': '<rootDir>/../packages/quill/packages/quill/src/index.ts',
        '^@posthog/quill-blocks$': '<rootDir>/../packages/quill/packages/blocks/src/index.ts',
        '^@posthog/quill-charts$': '<rootDir>/../packages/quill/packages/charts/src/index.ts',
        '^@posthog/quill-charts/testing$': '<rootDir>/../packages/quill/packages/charts/src/testing/index.ts',
        '^@posthog/quill-charts/story-helpers$': '<rootDir>/../packages/quill/packages/charts/src/story-helpers.tsx',
        '^@posthog/quill-components$': '<rootDir>/../packages/quill/packages/components/src/index.ts',
        '^@posthog/quill-components/metric$': '<rootDir>/../packages/quill/packages/components/src/metric.tsx',
        '^@posthog/quill-primitives$': '<rootDir>/../packages/quill/packages/primitives/src/index.ts',
        '^@posthog/quill-tokens$': '<rootDir>/../packages/quill/packages/tokens/src/index.ts',
        '^@posthog/shared-onboarding/(.*)$': '<rootDir>/../docs/onboarding/$1',
        d3: '<rootDir>/node_modules/d3/dist/d3.min.js',
        '^d3-(.*)$': `d3-$1/dist/d3-$1`,
        '^@mathjax/src/(.*)$': '<rootDir>/src/test/mocks/mathjaxMock.js',
    },

    // Emit JUnit XML for Trunk flaky-test detection only when JEST_JUNIT_OUTPUT_DIR is set.
    reporters: process.env.JEST_JUNIT_OUTPUT_DIR ? ['default', 'jest-junit'] : ['default'],

    // A path to a custom resolver — strips the `browser` export condition for the MSW ecosystem
    // (whose Node subpaths are null under `browser`) without affecting any other package's resolution.
    resolver: '<rootDir>/jest.resolver.js',

    modulePaths: ['<rootDir>/'],

    roots: rootDirectories(),

    setupFiles: ['<rootDir>/jest.polyfills.js', '<rootDir>/jest.setup.ts', 'fake-indexeddb/auto'],

    // jest.quarantine.ts first so it wraps the describe/it/test globals before any test file declares tests.
    setupFilesAfterEnv: [
        '<rootDir>/jest.quarantine.ts',
        '<rootDir>/../.github/scripts/jest-retries.cjs',
        '<rootDir>/jest.setupAfterEnv.ts',
        '<rootDir>/src/mocks/jest.ts',
    ],

    testEnvironment: 'jsdom',

    testEnvironmentOptions: {},

    testPathIgnorePatterns: [
        '/node_modules/',
        '/services/mcp/',
        '/products/[^/]+/frontend/e2e/',
        '/products/visual_review/cli/',
        '/products/desktop/',
    ],

    transform: {
        // Include .mjs/.cjs so ESM dependencies allowed through transformIgnorePatterns (e.g. MSW's) are transpiled.
        '\\.[cm]?[jt]sx?$': '@sucrase/jest-plugin',
        // The transformer just wraps file text as a string module, so it serves any raw
        // text import, not only YAML.
        '\\.yaml$': '<rootDir>/src/test/yamlRawTransformer.js',
        '\\.md$': '<rootDir>/src/test/yamlRawTransformer.js',
    },

    transformIgnorePatterns: [`node_modules/(?!.*(${esmModules.join('|')}))`],
}

export default config
