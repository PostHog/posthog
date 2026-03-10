module.exports = {
    testEnvironment: 'jsdom',
    transform: {
        '^.+\\.(t|j)sx?$': ['@swc/jest'],
    },
    testPathIgnorePatterns: ['/node_modules/', '/dist/'],
}
