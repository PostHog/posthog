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
        '<rootDir>/../packages/quill/packages/blocks/src',
    ]
}

const config: Config = {
    // All imported modules in your tests should be mocked automatically
    // automock: false,

    // Stop running tests after `n` failures
    // bail: 0,

    // The directory where Jest should store its cached dependency information
    // cacheDirectory: "/private/var/folders/30/3j86j9bx6514w18wx5gffc6r0000gn/T/jest_dx",

    // Automatically clear mock calls and instances between every test
    clearMocks: true,

    // Indicates whether the coverage information should be collected while executing the test
    // collectCoverage: false,

    // An array of glob patterns indicating a set of files for which coverage information should be collected
    // collectCoverageFrom: undefined,

    // The directory where Jest should output its coverage files
    coverageDirectory: 'coverage',

    // An array of regexp pattern strings used to skip coverage collection
    // coveragePathIgnorePatterns: [
    //   "/node_modules/"
    // ],

    // Indicates which provider should be used to instrument code for coverage
    coverageProvider: 'v8',

    // A list of reporter names that Jest uses when writing coverage reports
    // coverageReporters: [
    //   "json",
    //   "text",
    //   "lcov",
    //   "clover"
    // ],

    // An object that configures minimum threshold enforcement for coverage results
    // coverageThreshold: undefined,

    // A path to a custom dependency extractor
    // dependencyExtractor: undefined,

    // Make calling deprecated APIs throw helpful error messages
    // errorOnDeprecated: false,

    // Faking queueMicrotask starves the web-streams pump that MSW v2 response bodies ride on:
    // each pump microtask lands in the fake queue and respawns the next one, so any
    // advanceTimersByTimeAsync allocates unboundedly until the worker OOMs. Keep microtasks real.
    // Merged into per-test `jest.useFakeTimers({...})` configs unless they pass their own doNotFake.
    fakeTimers: {
        doNotFake: ['queueMicrotask'],
    },

    // Force coverage collection from ignored files using an array of glob patterns
    // forceCoverageMatch: [],

    // A path to a module which exports an async function that is triggered once before all test suites
    // globalSetup: undefined,

    // A path to a module which exports an async function that is triggered once after all test suites
    // globalTeardown: undefined,

    // The maximum amount of workers used to run your tests. Can be specified as % or a number. E.g. maxWorkers: 10% will use 10% of your CPU amount + 1 as the maximum worker number. maxWorkers: 2 will use a maximum of 2 workers.
    // maxWorkers: "50%",

    // An array of directory names to be searched recursively up from the requiring module's location
    // moduleDirectories: [
    //   "node_modules"
    // ],

    // An array of file extensions your modules use
    // moduleFileExtensions: [
    //   "js",
    //   "json",
    //   "jsx",
    //   "ts",
    //   "tsx",
    //   "node"
    // ],

    // A map from regular expressions to module names or to arrays of module names that allow to stub out resources with a single module
    moduleNameMapper: {
        '^.+\\.(css|less|scss|svg|png)$': '<rootDir>/src/test/mocks/styleMock.js',
        // @posthog/brand PNG subpaths resolve to .mjs modules that build a URL via
        // `new URL("./x.png", import.meta.url)` — import.meta is unavailable under Sucrase/CJS,
        // so mock them to the styleMock string instead of executing them.
        '^@posthog/brand/.*/png/.*$': '<rootDir>/src/test/mocks/styleMock.js',
        '^.+\\.sql\\?raw$': '<rootDir>/src/test/mocks/rawFileMock.js',
        '^(.+)\\.yaml\\?raw$': '$1.yaml',
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
        '^@posthog/quill$': '<rootDir>/../packages/quill/packages/quill/src/index.ts',
        '^@posthog/quill-blocks$': '<rootDir>/../packages/quill/packages/blocks/src/index.ts',
        '^@posthog/quill-charts$': '<rootDir>/../packages/quill/packages/charts/src/index.ts',
        '^@posthog/quill-charts/testing$': '<rootDir>/../packages/quill/packages/charts/src/testing/index.ts',
        '^@posthog/quill-charts/story-helpers$': '<rootDir>/../packages/quill/packages/charts/src/story-helpers.tsx',
        '^@posthog/quill-components$': '<rootDir>/../packages/quill/packages/components/src/index.ts',
        '^@posthog/quill-primitives$': '<rootDir>/../packages/quill/packages/primitives/src/index.ts',
        '^@posthog/quill-tokens$': '<rootDir>/../packages/quill/packages/tokens/src/index.ts',
        '^@posthog/shared-onboarding/(.*)$': '<rootDir>/../docs/onboarding/$1',
        d3: '<rootDir>/node_modules/d3/dist/d3.min.js',
        '^d3-(.*)$': `d3-$1/dist/d3-$1`,
        '^@mathjax/src/(.*)$': '<rootDir>/src/test/mocks/mathjaxMock.js',
    },

    // An array of regexp pattern strings, matched against all module paths before considered 'visible' to the module loader
    // modulePathIgnorePatterns: [],

    // Activates notifications for test results
    // notify: false,

    // An enum that specifies notification mode. Requires { notify: true }
    // notifyMode: "failure-change",

    // A preset that is used as a base for Jest's configuration
    // preset: undefined,

    // Run tests from one or more projects
    // projects: undefined,

    // Emit JUnit XML for Trunk flaky-test detection only when JEST_JUNIT_OUTPUT_DIR is set.
    reporters: process.env.JEST_JUNIT_OUTPUT_DIR ? ['default', 'jest-junit'] : ['default'],

    // Automatically reset mock state between every test
    // resetMocks: false,

    // Reset the module registry before running each individual test
    // resetModules: false,

    // A path to a custom resolver — strips the `browser` export condition for the MSW ecosystem
    // (whose Node subpaths are null under `browser`) without affecting any other package's resolution.
    resolver: '<rootDir>/jest.resolver.js',

    // Automatically restore mock state between every test
    // restoreMocks: false,

    // The root directory that Jest should scan for tests and modules within
    modulePaths: ['<rootDir>/'],

    // A list of paths to directories that Jest should use to search for files in
    roots: rootDirectories(),

    // Allows you to use a custom runner instead of Jest's default test runner
    // runner: "jest-runner",

    // The paths to modules that run some code to configure or set up the testing environment before each test
    setupFiles: ['<rootDir>/jest.polyfills.js', '<rootDir>/jest.setup.ts', 'fake-indexeddb/auto'],

    // A list of paths to modules that run some code to configure or set up the testing framework before each test
    setupFilesAfterEnv: ['<rootDir>/jest.setupAfterEnv.ts', '<rootDir>/src/mocks/jest.ts'],

    // The number of seconds after which a test is considered as slow and reported as such in the results.
    // slowTestThreshold: 5,

    // A list of paths to snapshot serializer modules Jest should use for snapshot testing
    // snapshotSerializers: [],

    // The test environment that will be used for testing
    testEnvironment: 'jsdom',

    // Options that will be passed to the testEnvironment
    testEnvironmentOptions: {},

    // Adds a location field to test results
    // testLocationInResults: false,

    // The glob patterns Jest uses to detect test files
    // testMatch: [
    //   "**/__tests__/**/*.[jt]s?(x)",
    //   "**/?(*.)+(spec|test).[tj]s?(x)"
    // ],

    // An array of regexp pattern strings that are matched against all test paths, matched tests are skipped
    testPathIgnorePatterns: [
        '/node_modules/',
        '/services/mcp/',
        '/products/[^/]+/frontend/e2e/',
        '/products/visual_review/cli/',
        '/products/agent_platform/services/',
        '/products/agent_platform/packages/',
    ],

    // The regexp pattern or array of patterns that Jest uses to detect test files
    // testRegex: [],

    // This option allows the use of a custom results processor
    // testResultsProcessor: undefined,

    // This option allows use of a custom test runner
    // testRunner: "jasmine2",

    // This option sets the URL for the jsdom environment. It is reflected in properties such as location.href
    // testURL: "http://localhost",

    // Setting this value to "fake" allows the use of fake timers for functions such as "setTimeout"
    // timers: "real",

    // A map from regular expressions to paths to transformers
    transform: {
        // Include .mjs/.cjs so ESM dependencies allowed through transformIgnorePatterns (e.g. MSW's) are transpiled.
        '\\.[cm]?[jt]sx?$': '@sucrase/jest-plugin',
        '\\.yaml$': '<rootDir>/src/test/yamlRawTransformer.js',
    },

    // An array of regexp pattern strings that are matched against all source file paths, matched files will skip transformation
    transformIgnorePatterns: [`node_modules/(?!.*(${esmModules.join('|')}))`],

    // An array of regexp pattern strings that are matched against all modules before the module loader will automatically return a mock for them
    // unmockedModulePathPatterns: undefined,

    // Indicates whether each individual test should be reported during the run
    // verbose: undefined,

    // An array of regexp patterns that are matched against all source file paths before re-running tests in watch mode
    // watchPathIgnorePatterns: [],

    // Whether to use watchman for file crawling
    // watchman: true,
}

export default config
