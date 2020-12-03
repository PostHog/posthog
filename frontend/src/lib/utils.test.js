import { formatLabel, identifierToHuman } from './utils'

describe('identifierToHuman()', () => {
    it('humanizes properly', () => {
        expect(identifierToHuman('testIdentifier')).toEqual('Test Identifier')
        expect(identifierToHuman('testIdentifierX')).toEqual('Test Identifier X')
        expect(identifierToHuman('something     ')).toEqual('Something')
        expect(identifierToHuman('  some_property')).toEqual('Some Property')
        expect(identifierToHuman(' Number666')).toEqual('Number 666')
        expect(identifierToHuman('7x')).toEqual('7x')
        expect(identifierToHuman('7X')).toEqual('7 X')
        expect(identifierToHuman('500')).toEqual('500')
        expect(identifierToHuman(404)).toEqual('404')
        expect(identifierToHuman('CreateProject')).toEqual('Create Project')
    })
})

describe('formatLabel()', () => {
    given('subject', () => formatLabel('some_event', given.action))

    given('action', () => ({}))

    it('formats the label', () => {
        expect(given.subject).toEqual('some_event (Total) ')
    })

    it('handles DAU queries', () => {
        given('action', () => ({ math: 'dau' }))

        expect(given.subject).toEqual('some_event (DAU) ')
    })

    it('handles summing by property', () => {
        given('action', () => ({ math: 'sum', math_property: 'event_property' }))

        expect(given.subject).toEqual('some_event (sum of event_property) ')
    })

    it('handles action with properties', () => {
        given('action', () => ({ properties: [{ value: 'hello' }, { operator: 'gt', value: 5 }] }))

        expect(given.subject).toEqual('some_event (Total)  (= hello, > 5)')
    })
})
