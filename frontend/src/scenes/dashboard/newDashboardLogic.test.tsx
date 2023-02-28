import { applyTemplate } from './newDashboardLogic'

describe('template function in newDashboardLogic', () => {
    it('ignores unused variables', () => {
        expect(
            applyTemplate({ a: 'hello', b: 'hi' }, [
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
    })
    it('uses identified variables', () => {
        expect(
            applyTemplate({ a: '{VARIABLE_1}', b: 'hi' }, [
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
