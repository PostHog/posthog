process.env.TZ = process.env.TZ || 'UTC'

const esmModules = [
    'query-selector-shadow-dom',
    'react-syntax-highlighter',
    '@react-hook',
    '@medv',
    'monaco-editor',
    '@posthog/hedgehog-mode',
    'mdast-util-find-and-replace',
    'escape-string-regexp',
    'unist-util-visit-parents',
    'unist-util-is',
    '@tiptap',
    'lowlight',
    'devlop',
    'hast-util-to-html',
    'html-void-elements',
    'property-information',
    'stringify-entities',
    'character-entities-html4',
    'character-entities-legacy',
    'ccount',
    'hast-util-whitespace',
    'space-separated-tokens',
    'comma-separated-tokens',
    'zwitch',
    '@posthog/hogql-parser',
]

/** @type {import('jest').Config} */
const config = {
    clearMocks: true,
    coverageDirectory: 'coverage',
    coverageProvider: 'v8',
    moduleNameMapper: {
        '^.+\\.(css|less|scss|svg|png|lottie)$': '<rootDir>/src/test/mocks/styleMock.js',
        '^.+\\.sql\\?raw$': '<rootDir>/src/test/mocks/rawFileMock.js',
        '^~/(.*)$': '<rootDir>/src/$1',
        '^@posthog/lemon-ui(|/.*)$': '<rootDir>/@posthog/lemon-ui/src/$1',
        '^lib/(.*)$': '<rootDir>/src/lib/$1',
        'monaco-editor': '<rootDir>/node_modules/monaco-editor/esm/vs/editor/editor.api.d.ts',
        '^scenes/(.*)$': '<rootDir>/src/scenes/$1',
        '^products/(.*)$': '<rootDir>/../products/$1',
        '^common/(.*)$': '<rootDir>/../common/$1',
        '^@posthog/shared-onboarding/(.*)$': '<rootDir>/../docs/onboarding/$1',
        '^@posthog/rrweb/es/rrweb': '@posthog/rrweb/dist/rrweb.min.js',
        d3: '<rootDir>/node_modules/d3/dist/d3.min.js',
        '^d3-(.*)$': `d3-$1/dist/d3-$1`,
    },
    modulePaths: ['<rootDir>/'],
    roots: ['<rootDir>/src', '<rootDir>/../products'],
    setupFiles: ['<rootDir>/jest.setup.ts', 'fake-indexeddb/auto'],
    setupFilesAfterEnv: ['<rootDir>/jest.setupAfterEnv.ts', 'givens/setup', '<rootDir>/src/mocks/jest.ts'],
    testEnvironment: 'jsdom',
    testEnvironmentOptions: {},
    testPathIgnorePatterns: ['/node_modules/', '/services/mcp/', '/products/error_tracking/'],
    transform: {
        '\\.[jt]sx?$': '@sucrase/jest-plugin',
    },
    transformIgnorePatterns: [`node_modules/(?!.*(${esmModules.join('|')}))`],
}

export default config
