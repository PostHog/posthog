import { template } from './DashboardTemplateVariables'

describe('DashboardTemplateVariables', () => {
    it('template works', () => {
        expect(template({ a: 'hello', b: 'hi' }, [{ id: 'a', name: 'a', default: 3 }])).toEqual({ a: 'hello', b: 'hi' })

        expect(template({ a: '{VARIABLE_1}', b: 'hi' }, [{ id: 'VARIABLE_1', name: 'a', default: 3 }])).toEqual({
            a: 3,
            b: 'hi',
        })
    })
})
