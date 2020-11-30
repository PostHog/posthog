const { pathsToModuleNameMapper } = require('ts-jest/utils')
const { readConfigFile } = require('typescript')
const { readFileSync } = require('fs')
const { config: tsconfig } = readConfigFile('./tsconfig.json', (path) => readFileSync(path, 'utf8'))

module.exports = {
    preset: 'ts-jest/presets/js-with-ts',
    testEnvironment: 'node',
    moduleNameMapper: pathsToModuleNameMapper(tsconfig.compilerOptions.paths /*, { prefix: '<rootDir>/' } */),
}
