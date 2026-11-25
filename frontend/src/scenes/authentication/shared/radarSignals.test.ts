jest.mock('@workos/radar-signals', () => ({
    WorkOSRadar: { init: jest.fn(() => ({ getToken: () => Promise.resolve('signals_abc') })) },
}))

type RadarSignalsModule = typeof import('./radarSignals')

describe('radarSignals', () => {
    let radarSignals: RadarSignalsModule

    beforeEach(() => {
        jest.useFakeTimers({ doNotFake: ['nextTick', 'setImmediate', 'queueMicrotask'] })
        jest.isolateModules(() => {
            radarSignals = require('./radarSignals')
        })
        radarSignals.startRadarSignals('client_123')
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each([
        ['gives a fresh token', () => undefined, 'signals_abc'],
        ['gives no token after one login sent it', () => radarSignals.markRadarSignalsIdSent('signals_abc'), ''],
        ['gives no token once it is older than 55 minutes', () => jest.advanceTimersByTime(55 * 60 * 1000 + 1), ''],
    ])('%s', async (_name, before, expected) => {
        before()

        expect(await radarSignals.getRadarSignalsId()).toBe(expected)
    })
})
