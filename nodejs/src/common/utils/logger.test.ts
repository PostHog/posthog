import { Logger } from './logger'

describe('Logger', () => {
    let logger: Logger

    beforeEach(() => {
        logger = new Logger('test')
        jest.spyOn(logger['pino'], 'info')
        jest.spyOn(logger['pino'], 'debug')
        jest.spyOn(logger['pino'], 'warn')
        jest.spyOn(logger['pino'], 'error')
    })

    it('should log', () => {
        logger.info('test')
        expect(jest.mocked(logger['pino'].info).mock.lastCall).toMatchInlineSnapshot(`
            [
              {
                "msg": "[TEST] test",
              },
            ]
        `)
    })

    it('should merge multiple values', () => {
        logger.info('test', 2, new Error('error'), { extra: 'extra' })
        expect(jest.mocked(logger['pino'].info).mock.lastCall).toMatchInlineSnapshot(`
            [
              {
                "extra": "extra",
                "msg": "[TEST] test 2 Error: error",
              },
            ]
        `)
    })

    it('should handle error values', () => {
        logger.info(new Error('error'))
        expect(jest.mocked(logger['pino'].info).mock.lastCall).toMatchInlineSnapshot(`
            [
              {
                "msg": "[TEST] Error: error",
              },
            ]
        `)
    })

    it('should nicely serialise error values', () => {
        logger.info('Errored!!!', {
            error: new Error('nested error'),
            another: new Error('another error'),
        })
        expect(jest.mocked(logger['pino'].info).mock.lastCall).toMatchInlineSnapshot(`
            [
              {
                "another": [Error: another error],
                "error": [Error: nested error],
                "msg": "[TEST] Errored!!!",
              },
            ]
        `)
    })

    // Entrypoints without plugin-server database env (e.g. the recording rasterizer)
    // import this module transitively. Guards against reintroducing a defaultConfig
    // import, which throws at module load when that env is missing. NODE_ENV must be
    // production here: in the test env, config falls back to a default DATABASE_URL,
    // so the throw this test guards against would never fire.
    it('loads without plugin-server database env', async () => {
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
        let isolated: typeof import('./logger') | undefined
        try {
            jest.isolateModules(() => {
                isolated = require('./logger')
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
        expect(isolated!.logger).toBeInstanceOf(isolated!.Logger)
        await isolated!.shutdownLogger()
    })
})
