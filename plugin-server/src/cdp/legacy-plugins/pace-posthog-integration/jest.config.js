const { pathsToModuleNameMapper } = require('ts-jest/utils')
const { compilerOptions } = require('./tsconfig')

const moduleNameMapper = undefined
if (compilerOptions.paths) {
    moduleNameMapper = pathsToModuleNameMapper(compilerOptions.paths, { prefix: 'src/' })
}

module.exports = {
    preset: 'ts-jest',
    testEnvironment: 'node',
    moduleNameMapper,
}
