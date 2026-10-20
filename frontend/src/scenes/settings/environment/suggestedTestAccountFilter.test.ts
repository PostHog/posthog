import { suggestedTestAccountFilterOf } from './suggestedTestAccountFilter'

const rule = { key: '$host', type: 'event', operator: 'is_not', value: ['localhost:8000'] }

describe('suggestedTestAccountFilterOf', () => {
    it.each<[string, unknown, unknown]>([
        ['the rule the data checks suggest', rule, rule],
        ['a rule with extra fields, without them', { ...rule, label: 'x' }, rule],
        ['a behavioral rule, which renders other fields', { ...rule, type: 'behavioral', event_filters: 'x' }, null],
        ['a rule whose values are not strings', { ...rule, value: [{}] }, null],
        ['a rule with another operator', { ...rule, operator: 'icontains', value: 'localhost' }, null],
        ['a parameter that is not JSON', '{not json', null],
    ])('reads %s', (_name, param, expected) => {
        const raw = typeof param === 'string' ? param : JSON.stringify(param)
        expect(suggestedTestAccountFilterOf({ suggested_test_account_filter: raw })).toEqual(expected)
    })
})
