import { dayjs } from 'lib/dayjs'

import { ExceptionStepLoader } from './exceptionSteps'

describe('ExceptionStepLoader', () => {
    it('skips malformed steps and keeps valid steps sorted by timestamp', async () => {
        const loader = new ExceptionStepLoader('exception-uuid', {
            $lib: 'web',
            $exception_steps: [
                {
                    message: 'Second valid step',
                    timestamp: '2024-07-09T12:00:04.000Z',
                    level: 'info',
                },
                {
                    bad: 'row',
                },
                {
                    message: 'First valid step',
                    timestamp: '2024-07-09T12:00:02.000Z',
                    type: 'ui.interaction',
                },
                {
                    message: '',
                    timestamp: '2024-07-09T12:00:05.000Z',
                },
            ],
        } as any)

        const before = await loader.loadBefore(dayjs.utc('2024-07-09T12:00:06.000Z'), 10)

        expect(before.items.map((item) => item.payload.message)).toEqual(['First valid step', 'Second valid step'])
        expect(before.items.map((item) => item.timestamp.toISOString())).toEqual([
            '2024-07-09T12:00:02.000Z',
            '2024-07-09T12:00:04.000Z',
        ])
    })

    it('supports cursor-based pagination through loadAfter and loadBefore', async () => {
        const loader = new ExceptionStepLoader('exception-uuid', {
            $lib: 'web',
            $exception_steps: [
                {
                    message: 'Step A',
                    timestamp: '2024-07-09T12:00:01.000Z',
                },
                {
                    message: 'Step B',
                    timestamp: '2024-07-09T12:00:02.000Z',
                },
                {
                    message: 'Step C',
                    timestamp: '2024-07-09T12:00:03.000Z',
                },
            ],
        } as any)

        const after = await loader.loadAfter(dayjs.utc('2024-07-09T12:00:01.500Z'), 1)
        const before = await loader.loadBefore(dayjs.utc('2024-07-09T12:00:02.500Z'), 1)

        expect(after.items.map((item) => item.payload.message)).toEqual(['Step B'])
        expect(before.items.map((item) => item.payload.message)).toEqual(['Step B'])
    })
})
