import type { Config } from 'jest'

import baseConfig from './jest.config'

const config: Config = {
    ...baseConfig,
    setupFiles: ['<rootDir>/jest.probe.retainMaps.js', ...(baseConfig.setupFiles ?? [])],
}

export default config
