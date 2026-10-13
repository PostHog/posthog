import type { Config } from 'jest'

import base from './jest.config'

const config: Config = {
    ...base,
    dependencyExtractor: '<rootDir>/jest.probe.dependencyExtractor.js',
}

export default config
