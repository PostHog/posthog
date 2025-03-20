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
})
