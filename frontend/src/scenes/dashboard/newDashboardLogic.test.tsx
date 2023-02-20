import { template } from './newDashboardLogic'

describe('template function in newDashboardLogic', () => {
    it('template works', () => {
        expect(
            template({ a: 'hello', b: 'hi' }, [
                {
                    id: 'VARIABLE_1',
                    name: 'a',
                    default: {
                        event: '$pageview',
                    },
                    description: 'The description of the variable',
                    required: true,
                    type: 'event',
                },
            ])
        ).toEqual({ a: 'hello', b: 'hi' })

        expect(
            template({ a: '{VARIABLE_1}', b: 'hi' }, [
                {
                    id: 'VARIABLE_1',
                    name: 'a',
                    default: {
                        event: '$pageview',
                    },
                    description: 'The description of the variable',
                    required: true,
                    type: 'event',
                },
            ])
        ).toEqual({
            a: {
                event: '$pageview',
            },
            b: 'hi',
        })
    })
})
