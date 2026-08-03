// The rasterizer deployment has no plugin-server database env, so its whole import
// graph must load without it. Guards the otlp metrics chain (shared instruments,
// provider, exporter, logger) against reintroducing a module that evaluates
// defaultConfig at load, which crashloops the worker at boot. NODE_ENV must be
// production here: in the test env, config falls back to a default DATABASE_URL,
// so the throw this test guards against would never fire.
describe('otel-metrics import chain', () => {
    it('loads without plugin-server database env', () => {
        const saved: Record<string, string | undefined> = {
            NODE_ENV: process.env.NODE_ENV,
            DEBUG: process.env.DEBUG,
            DATABASE_URL: process.env.DATABASE_URL,
            POSTHOG_DB_NAME: process.env.POSTHOG_DB_NAME,
        }
        process.env.NODE_ENV = 'production'
        delete process.env.DEBUG
        delete process.env.DATABASE_URL
        delete process.env.POSTHOG_DB_NAME
        let mod: typeof import('../otel-metrics') | undefined
        try {
            jest.isolateModules(() => {
                mod = require('../otel-metrics')
            })
        } finally {
            for (const [key, value] of Object.entries(saved)) {
                if (value === undefined) {
                    delete process.env[key]
                } else {
                    process.env[key] = value
                }
            }
        }
        expect(mod!.initMetrics).toBeInstanceOf(Function)
    })
})
