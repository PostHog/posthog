import { MakeLogicType, actions, kea, listeners, path, reducers } from 'kea'

import { initKeaTests } from '~/test/init'

type breakpointTestLogicType = MakeLogicType<
    { completedValue: string | null },
    {
        start: (value: string) => { value: string }
        complete: (value: string) => { value: string }
    }
>

const breakpointTestLogic = kea<breakpointTestLogicType>([
    path(['test', 'keaTestListeners', 'breakpointTestLogic']),
    actions({
        start: (value: string) => ({ value }),
        complete: (value: string) => ({ value }),
    }),
    reducers({
        completedValue: [null as string | null, { complete: (_, { value }) => value }],
    }),
    listeners(({ actions }) => ({
        start: async ({ value }, breakpoint) => {
            await breakpoint(60_000)
            actions.complete(value)
        },
    })),
])

const legacyBreakpointTestLogic = kea<breakpointTestLogicType>({
    path: ['test', 'keaTestListeners', 'legacyBreakpointTestLogic'],
    actions: {
        start: (value: string) => ({ value }),
        complete: (value: string) => ({ value }),
    },
    reducers: {
        completedValue: [null as string | null, { complete: (_, { value }) => value }],
    },
    listeners: ({ actions }) => ({
        start: async ({ value }, breakpoint) => {
            await breakpoint(60_000)
            actions.complete(value)
        },
    }),
})

describe('Kea test listeners', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each([
        ['builder-form logic', breakpointTestLogic],
        ['legacy object-form logic', legacyBreakpointTestLogic],
    ])('runs delayed breakpoints on the next timer task and keeps cancellation for %s', async (_, logicBuilder) => {
        const setTimeoutSpy = jest.spyOn(global, 'setTimeout').mockImplementation((callback, delay, ...args) => {
            if (delay === 0) {
                callback(...args)
            }
            return 0 as unknown as NodeJS.Timeout
        })
        const logic = logicBuilder()
        logic.mount()

        logic.actions.start('first')
        logic.actions.start('second')
        await Promise.resolve()
        await Promise.resolve()

        expect(setTimeoutSpy).toHaveBeenCalledTimes(2)
        expect(setTimeoutSpy).toHaveBeenCalledWith(expect.any(Function), 0)
        expect(logic.values.completedValue).toBe('second')
    })
})
