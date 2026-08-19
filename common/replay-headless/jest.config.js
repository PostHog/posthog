module.exports = {
    testEnvironment: 'jsdom',
    transform: {
        '^.+\\.(t|j)sx?$': ['@swc/jest'],
    },
    // posthog-js's rrweb subpath entries are shipped as ESM; let them through to the transform.
    transformIgnorePatterns: ['node_modules/(?!.*posthog-js/dist/rrweb)'],
    testPathIgnorePatterns: ['/node_modules/', '/dist/'],
}
