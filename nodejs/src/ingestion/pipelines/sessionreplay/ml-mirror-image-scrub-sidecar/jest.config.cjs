module.exports = {
    testEnvironment: 'node',
    testMatch: ['<rootDir>/src/**/*.test.ts'],
    // The sources import each other with explicit `.ts` extensions (tsx style); strip the extension so
    // jest resolves the .ts file (moduleFileExtensions includes 'ts' by default).
    // jest-resolve can't resolve zxing-wasm's `.wasm` export subpaths (node proper can); map them.
    moduleNameMapper: {
        '^(\\.{1,2}/.*)\\.ts$': '$1',
        '^zxing-wasm/reader/zxing_reader\\.wasm$': '<rootDir>/node_modules/zxing-wasm/dist/reader/zxing_reader.wasm',
        '^zxing-wasm/writer/zxing_writer\\.wasm$': '<rootDir>/node_modules/zxing-wasm/dist/writer/zxing_writer.wasm',
    },
}
