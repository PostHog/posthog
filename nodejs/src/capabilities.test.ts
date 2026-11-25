import { PluginServerCapabilities } from './types'

describe('default capabilities', () => {
    const originalEnv = process.env

    afterEach(() => {
        process.env = originalEnv
    })

    const defaultCapabilities = (env: Record<string, string>): PluginServerCapabilities => {
        process.env = { ...originalEnv, CLOUD_DEPLOYMENT: '', DEBUG: '', ...env }
        let capabilities: PluginServerCapabilities = {}
        jest.isolateModules(() => {
            const { getPluginServerCapabilities } = require('./capabilities')
            capabilities = getPluginServerCapabilities({ PLUGIN_SERVER_MODE: null, NODEJS_CAPABILITY_GROUPS: '' })
        })
        return capabilities
    }

    it.each([
        ['a self-hosted production install', { NODE_ENV: 'production' }, true],
        ['local development', { NODE_ENV: 'development' }, true],
        ['PostHog Cloud', { NODE_ENV: 'production', CLOUD_DEPLOYMENT: 'US' }, false],
        ['the test environment', { NODE_ENV: 'test' }, false],
    ])('decides whether the default process runs the Cyclotron janitor on %s', (_name, env, expected) => {
        expect(!!defaultCapabilities(env).cdpCyclotronV2Janitor).toBe(expected)
    })
})
