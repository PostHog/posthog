import { formatLabel, identifierToHuman, midEllipsis, isURL, capitalizeFirstLetter, compactNumber } from './utils'

describe('capitalizeFirstLetter()', () => {
    it('returns the capitalized string', () => {
        expect(capitalizeFirstLetter('jane')).toEqual('Jane')
        expect(capitalizeFirstLetter('hello there!')).toEqual('Hello there!')
        expect(capitalizeFirstLetter('underscores_make_no_difference')).toEqual('Underscores_make_no_difference')
    })
})

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

    describe('DAU queries', () => {
        given('action', () => ({ math: 'dau' }))

        it('is formatted', () => {
            expect(given.subject).toEqual('some_event (Active Users) ')
        })
    })

    describe('summing by property', () => {
        given('action', () => ({ math: 'sum', math_property: 'event_property' }))

        it('is formatted', () => {
            expect(given.subject).toEqual('some_event (sum of event_property) ')
        })
    })

    describe('action with properties', () => {
        given('action', () => ({ properties: [{ value: 'hello' }, { operator: 'gt', value: 5 }] }))

        it('is formatted', () => {
            expect(given.subject).toEqual('some_event (Total)  (= hello, > 5)')
        })
    })
})

describe('midEllipsis()', () => {
    it('returns same string if short', () => {
        expect(midEllipsis('1234567890', 10)).toEqual('1234567890')
    })

    it('formats string properly', () => {
        expect(midEllipsis('1234567890', 2)).toEqual('1...0')
        expect(midEllipsis('1234567890', 4)).toEqual('12...90')
        expect(midEllipsis('1234567890', 8)).toEqual('1234...7890')
        expect(midEllipsis('ZgZbZgD9Z4U2FsohDYAJ-hMdoxY7-oSdWwrEWtdBeM', 26)).toEqual('ZgZbZgD9Z4U2F...oSdWwrEWtdBeM')
        expect(midEllipsis('ZgZbZgD9Z4U2FsohDYAJ-hMdoxY7-oSdWwrEWtdBeM', 25).length).toBeLessThanOrEqual(28) // 25 + 3 (...)
    })
})

describe('isURL()', () => {
    it('recognizes URLs propertly', () => {
        expect(isURL('https://www.posthog.com')).toEqual(true)
        expect(isURL('http://www.posthog.com')).toEqual(true)
        expect(isURL('http://www.posthog.com:8000/images')).toEqual(true)
    })

    it('recognizes non-URLs propertly', () => {
        expect(isURL('1234567890')).toEqual(false)
        expect(isURL('www.posthog')).toEqual(false)
        expect(isURL('http://posthog')).toEqual(false)
        expect(isURL('-.posthog')).toEqual(false)
        expect(isURL('posthog.3')).toEqual(false)
        expect(isURL(1)).toEqual(false)
        expect(isURL(true)).toEqual(false)
        expect(isURL(null)).toEqual(false)
    })
})

describe('compactNumber()', () => {
    it('formats number correctly', () => {
        expect(compactNumber(10)).toEqual('10')
        expect(compactNumber(293)).toEqual('293')
        expect(compactNumber(5001)).toEqual('5K')
        expect(compactNumber(5312)).toEqual('5.3K')
        expect(compactNumber(5392)).toEqual('5.4K')
        expect(compactNumber(2833102, 2)).toEqual('2.83M')
        expect(compactNumber(8283310234)).toEqual('8.3B')
    })
})
