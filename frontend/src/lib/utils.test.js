import dayjs from 'dayjs'
import {
    formatLabel,
    identifierToHuman,
    midEllipsis,
    isURL,
    capitalizeFirstLetter,
    compactNumber,
    pluralize,
    endWithPunctation,
    dateFilterToText,
    hexToRGBA,
    average,
    median,
} from './utils'

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
        expect(given.subject).toEqual('some_event')
    })

    describe('DAU queries', () => {
        given('action', () => ({ math: 'dau' }))

        it('is formatted', () => {
            expect(given.subject).toEqual('some_event (Unique users) ')
        })
    })

    describe('summing by property', () => {
        given('action', () => ({ math: 'sum', math_property: 'event_property' }))

        it('is formatted', () => {
            expect(given.subject).toEqual('some_event (sum of event_property) ')
        })
    })

    describe('action with properties', () => {
        given('action', () => ({
            properties: [
                { value: 'hello', key: 'greeting' },
                { operator: 'gt', value: 5 },
            ],
        }))

        it('is formatted', () => {
            expect(given.subject).toEqual('some_event (greeting = hello, > 5)')
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
        expect(compactNumber(5312)).toEqual('5.31K')
        expect(compactNumber(5392)).toEqual('5.39K')
        expect(compactNumber(2833102)).toEqual('2.83M')
        expect(compactNumber(8283310234)).toEqual('8.28B')
    })
})
describe('pluralize()', () => {
    it('handles singular cases', () => {
        expect(pluralize(1, 'member')).toEqual('1 member')
        expect(pluralize(1, 'bacterium', 'bacteria', true)).toEqual('1 bacterium')
        expect(pluralize(1, 'word', null, false)).toEqual('word')
    })
    it('handles plural cases', () => {
        expect(pluralize(28321, 'member')).toEqual('28321 members')
        expect(pluralize(99, 'bacterium', 'bacteria')).toEqual('99 bacteria')
        expect(pluralize(3, 'word', null, false)).toEqual('words')
    })
})

describe('endWithPunctation()', () => {
    it('adds period at the end when needed', () => {
        expect(endWithPunctation('Hello')).toEqual('Hello.')
        expect(endWithPunctation('Learn more! ')).toEqual('Learn more!')
        expect(endWithPunctation('Stop.')).toEqual('Stop.')
        expect(endWithPunctation(null)).toEqual('')
        expect(endWithPunctation('   ')).toEqual('')
        expect(endWithPunctation('  Why? ')).toEqual('Why?')
    })
})

describe('dateFilterToText()', () => {
    it('handles dayjs dates', () => {
        const from = dayjs('2018-04-04T16:00:00.000Z')
        const to = dayjs('2018-04-09T15:05:00.000Z')

        expect(dateFilterToText(from, to, 'custom')).toEqual('2018-04-04 - 2018-04-09')
    })

    it('handles various ranges', () => {
        expect(dateFilterToText('dStart', null, 'default')).toEqual('Today')
        expect(dateFilterToText('2020-01-02', '2020-01-05', 'default')).toEqual('2020-01-02 - 2020-01-05')
        expect(dateFilterToText(null, null, 'default')).toEqual('default')
        expect(dateFilterToText('-24h', null, 'default')).toEqual('Last 24 hours')
        expect(dateFilterToText('-48h', undefined, 'default')).toEqual('Last 48 hours')
        expect(dateFilterToText('-1d', 'dStart', 'default')).toEqual('Yesterday')
        expect(dateFilterToText('-1mStart', '-1mEnd', 'default')).toEqual('Previous month')
    })
})

describe('hexToRGBA()', () => {
    it('converts hex to RGBA correctly', () => {
        expect(hexToRGBA('#ff0000', 0.3)).toEqual('rgba(255,0,0,0.3)')
        expect(hexToRGBA('#0000Cc', 0)).toEqual('rgba(0,0,204,0)')
        expect(hexToRGBA('#5375ff', 1)).toEqual('rgba(83,117,255,1)')
    })
})

describe('average()', () => {
    it('calculates average correctly', () => {
        expect(average([9, 4, 1, 3, 5, 7])).toEqual(4.8)
        expect(average([72, 35, 68, 66, 70, 9, 81])).toEqual(57.3) // Tests rounding too
        expect(average([86.4, 46.321, 45.304, 34.1, 147])).toEqual(71.8) // Tests rounding too
    })
})

describe('median()', () => {
    it('returns middle number if array length is odd', () => {
        expect(median([9, 4, 1, 3, 5, 7, 3, 6, 14])).toEqual(5)
    })
    it('returns avg of middle numbers if array length is even', () => {
        expect(median([9, 4, 0, 5, 7, 3, 6, 14])).toEqual(5.5)
    })
})
