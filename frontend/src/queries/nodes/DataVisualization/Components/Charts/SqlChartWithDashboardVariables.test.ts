import { Variable, VariableType } from '../../types'
import { singleFilterableVariable } from './SqlChartWithDashboardVariables'

const variable = (id: string, type: VariableType): Variable =>
    ({ id, name: id, code_name: id, type, default_value: '' }) as Variable

describe('singleFilterableVariable', () => {
    it('returns the sole String or List variable', () => {
        const account = variable('account', 'String')
        expect(singleFilterableVariable([account, variable('count', 'Number')])).toBe(account)
    })

    it('returns null when the query uses no String or List variable', () => {
        expect(singleFilterableVariable([variable('count', 'Number'), variable('since', 'Date')])).toBeNull()
    })

    it('returns null when several candidates make the target ambiguous', () => {
        expect(singleFilterableVariable([variable('account', 'String'), variable('plan', 'List')])).toBeNull()
    })
})
