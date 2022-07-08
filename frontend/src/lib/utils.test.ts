import tk from 'timekeeper'
import {
    areObjectValuesEmpty,
    average,
    capitalizeFirstLetter,
    colonDelimitedDuration,
    compactNumber,
    dateFilterToText,
    endWithPunctation,
    ensureStringIsNotBlank,
    formatLabel,
    hexToRGBA,
    humanFriendlyDuration,
    identifierToHuman,
    isURL,
    median,
    midEllipsis,
    objectDiffShallow,
    pluralize,
    toParams,
    eventToDescription,
    ceilMsToClosestSecond,
    floorMsToClosestSecond,
    dateMappingExperiment as dateMapping,
    getFormattedLastWeekDate,
    genericOperatorMap,
    dateTimeOperatorMap,
    stringOperatorMap,
    numericOperatorMap,
    chooseOperatorMap,
    booleanOperatorMap,
    roundToDecimal,
    convertPropertyGroupToProperties,
    convertPropertiesToPropertyGroup,
    calculateDays,
    range,
    durationOperatorMap,
    isExternalLink,
} from './utils'
import { ActionFilter, ElementType, FilterLogicalOperator, PropertyOperator, PropertyType, TimeUnitType } from '~/types'
import { dayjs } from 'lib/dayjs'

describe('toParams', () => {
    it('handles unusual input', () => {
        expect(toParams({})).toEqual('')
        expect(toParams([])).toEqual('')
        expect(toParams(undefined as any)).toEqual('')
        expect(toParams(null as any)).toEqual('')
    })

    it('is tolerant of empty objects', () => {
        const left = toParams({ a: 'b', ...{}, b: 'c' })
        const right = toParams({ a: 'b', ...{}, ...{}, b: 'c' })
        expect(left).toEqual(right)
    })

    it('can handle numeric values', () => {
        const actual = toParams({ a: 123 })
        expect(actual).toEqual('a=123')
    })

    it('encodes arrays as a single query param', () => {
        const actual = toParams({ include: ['a', 'b'] })
        expect(actual).toEqual('include=%5B%22a%22%2C%22b%22%5D')
    })

    it('can explode arrays to individual parameters', () => {
        const actual = toParams({ include: ['a', 'b'] }, true)
        expect(actual).toEqual('include=a&include=b')
    })
})

describe('capitalizeFirstLetter()', () => {
    it('returns the capitalized string', () => {
        expect(capitalizeFirstLetter('jane')).toEqual('Jane')
        expect(capitalizeFirstLetter('hello there!')).toEqual('Hello there!')
        expect(capitalizeFirstLetter('underscores_make_no_difference')).toEqual('Underscores_make_no_difference')
    })
})

describe('identifierToHuman()', () => {
    it('humanizes properly', () => {
        expect(identifierToHuman('testIdentifier')).toEqual('Test identifier')
        expect(identifierToHuman('testIdentifierX')).toEqual('Test identifier x')
        expect(identifierToHuman('something     ')).toEqual('Something')
        expect(identifierToHuman('  some_property')).toEqual('Some property')
        expect(identifierToHuman(' Number666')).toEqual('Number 666')
        expect(identifierToHuman('7x')).toEqual('7x')
        expect(identifierToHuman('7X')).toEqual('7 x')
        expect(identifierToHuman('500')).toEqual('500')
        expect(identifierToHuman(404)).toEqual('404')
        expect(identifierToHuman('CreateProject')).toEqual('Create project')
    })
})

describe('formatLabel()', () => {
    const action: ActionFilter = {
        id: 123,
        name: 'Test Action',
        properties: [],
        type: 'actions',
    }

    it('formats the label', () => {
        expect(formatLabel('some_event', action)).toEqual('some_event')
    })

    it('DAU queries', () => {
        expect(formatLabel('some_event', { ...action, math: 'dau' })).toEqual('some_event (Unique users)')
    })

    it('summing by property', () => {
        expect(formatLabel('some_event', { ...action, math: 'sum', math_property: 'event_property' })).toEqual(
            'some_event (sum of event_property)'
        )
    })

    it('action with properties', () => {
        expect(
            formatLabel('some_event', {
                ...action,
                properties: [
                    { value: 'hello', key: 'greeting', operator: PropertyOperator.Exact, type: '' },
                    { operator: PropertyOperator.GreaterThan, value: 5, key: '', type: '' },
                ],
            })
        ).toEqual('some_event (greeting = hello, > 5)')
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
    it('recognizes URLs properly', () => {
        expect(isURL('https://www.posthog.com')).toEqual(true)
        expect(isURL('http://www.posthog.com')).toEqual(true)
        expect(isURL('http://www.posthog.com:8000/images')).toEqual(true)
        expect(isURL('http://localhost:8000/login?next=/insights')).toEqual(true)
        expect(isURL('http://localhost:8000/events?properties=%5B%5D')).toEqual(true)
        expect(isURL('https://apple.com/')).toEqual(true)
        expect(isURL('https://stripe.com')).toEqual(true)
        expect(isURL('https://spotify.com')).toEqual(true)
        expect(isURL('https://sevenapp.events/')).toEqual(true)
        expect(isURL('https://seven-stagingenv.web.app/')).toEqual(true)
        expect(isURL('https://salesforce.co.uk/')).toEqual(true)
    })

    it('recognizes non-URLs properly', () => {
        expect(isURL('1234567890')).toEqual(false)
        expect(isURL('www.posthog')).toEqual(false)
        expect(isURL('-.posthog')).toEqual(false)
        expect(isURL('posthog.3')).toEqual(false)
        expect(isURL(1)).toEqual(false)
        expect(isURL(true)).toEqual(false)
        expect(isURL(null)).toEqual(false)
    })
})

describe('isExternalLink()', () => {
    it('recognizes external links properly', () => {
        expect(isExternalLink('http://www.posthog.com')).toEqual(true)
        expect(isExternalLink('https://www.posthog.com')).toEqual(true)
        expect(isExternalLink('mailto:ben@posthog.com')).toEqual(true)
    })

    it('recognizes non-external links properly', () => {
        expect(isExternalLink('path')).toEqual(false)
        expect(isExternalLink('/path')).toEqual(false)
        expect(isExternalLink(1)).toEqual(false)
        expect(isExternalLink(true)).toEqual(false)
        expect(isExternalLink(null)).toEqual(false)
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
        expect(compactNumber(null)).toEqual('-')
    })
})

describe('roundToDecimal()', () => {
    it('formats number correctly', () => {
        expect(roundToDecimal(null)).toEqual('-')
        expect(roundToDecimal(293)).toEqual('293.00')
        expect(roundToDecimal(102.121233)).toEqual('102.12')
        expect(roundToDecimal(102.99999)).toEqual('103.00')
        expect(roundToDecimal(1212)).toEqual('1212.00')
        expect(roundToDecimal(1212, 3)).toEqual('1212.000')
    })
})

describe('pluralize()', () => {
    it('handles singular cases', () => {
        expect(pluralize(1, 'member')).toEqual('1 member')
        expect(pluralize(1, 'bacterium', 'bacteria', true)).toEqual('1 bacterium')
        expect(pluralize(1, 'word', undefined, false)).toEqual('word')
    })
    it('handles plural cases', () => {
        expect(pluralize(28321, 'member')).toEqual('28,321 members')
        expect(pluralize(99, 'bacterium', 'bacteria')).toEqual('99 bacteria')
        expect(pluralize(3, 'word', undefined, false)).toEqual('words')
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

describe('getFormattedLastWeekDate()', () => {
    it('happy case', () => {
        tk.freeze(new Date(1330688329321))
        expect(getFormattedLastWeekDate()).toEqual('January 13 - March 2, 2012')
        tk.reset()
    })
})

describe('dateFilterToText()', () => {
    describe('not formatted', () => {
        it('handles dayjs dates', () => {
            const from = dayjs('2018-04-04T16:00:00.000Z')
            const to = dayjs('2018-04-09T15:05:00.000Z')

            expect(dateFilterToText(from, to, 'custom')).toEqual('April 4 - April 9, 2018')
        })

        it('handles various ranges', () => {
            expect(dateFilterToText('dStart', null, 'default')).toEqual('Today')
            expect(dateFilterToText('2020-01-02', '2020-01-05', 'default')).toEqual('2020-01-02 - 2020-01-05')
            expect(dateFilterToText(null, null, 'default')).toEqual('default')
            expect(dateFilterToText('-24h', null, 'default')).toEqual('Last 24 hours')
            expect(dateFilterToText('-48h', undefined, 'default')).toEqual('Last 48 hours')
            expect(dateFilterToText('-1d', '-1d', 'default')).toEqual('Yesterday')
            expect(dateFilterToText('-1mStart', '-1mEnd', 'default')).toEqual('Previous month')
        })

        it('can have overridden date options', () => {
            expect(dateFilterToText('-21d', null, 'default', [{ key: 'Last 3 weeks', values: ['-21d'] }])).toEqual(
                'Last 3 weeks'
            )
        })
    })

    describe('formatted', () => {
        it('handles dayjs dates', () => {
            const from = dayjs('2018-04-04T16:00:00.000Z')
            const to = dayjs('2018-04-09T15:05:00.000Z')

            expect(dateFilterToText(from, to, 'custom', dateMapping, true)).toEqual('April 4 - April 9, 2018')
        })

        it('handles various ranges', () => {
            tk.freeze(new Date(1330688329321))
            expect(dateFilterToText('dStart', null, 'default', dateMapping, true)).toEqual('March 2, 2012')
            expect(dateFilterToText('2020-01-02', '2020-01-05', 'default', dateMapping, true)).toEqual(
                'January 2 - January 5, 2020'
            )
            expect(dateFilterToText(null, null, 'default', dateMapping, true)).toEqual('default')
            expect(dateFilterToText('-24h', null, 'default', dateMapping, true)).toEqual('March 1 - March 2, 2012')
            expect(dateFilterToText('-48h', undefined, 'default', dateMapping, true)).toEqual(
                'February 29 - March 2, 2012'
            )
            expect(dateFilterToText('-1d', null, 'default', dateMapping, true)).toEqual('March 1, 2012')
            expect(dateFilterToText('-1mStart', '-1mEnd', 'default', dateMapping, true)).toEqual(
                'March 1 - March 31, 2012'
            )
            expect(dateFilterToText('-180d', null, 'default', dateMapping, true)).toEqual(
                'September 4, 2011 - March 2, 2012'
            )
            tk.reset()
        })

        it('can have overridden date options', () => {
            tk.freeze(new Date(1330688329321))
            expect(
                dateFilterToText(
                    '-21d',
                    null,
                    'default',
                    [{ key: 'Last 3 weeks', values: ['-21d'], getFormattedDate: () => 'custom formatted date' }],
                    true
                )
            ).toEqual('custom formatted date')
            tk.reset()
        })

        it('can have overridden date format', () => {
            const from = dayjs('2018-04-04T16:00:00.000Z').tz('America/New_York')
            const to = dayjs('2018-04-09T15:05:00.000Z').tz('America/New_York')

            expect(dateFilterToText(from, to, 'custom', dateMapping, true, 'YYYY-MM-DD hh:mm:ss')).toEqual(
                '2018-04-04 12:00:00 - 2018-04-09 11:05:00'
            )
        })
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

describe('humanFriendlyDuration()', () => {
    it('returns correct value for <= 60', () => {
        expect(humanFriendlyDuration(60)).toEqual('1m')
        expect(humanFriendlyDuration(45)).toEqual('45s')
        expect(humanFriendlyDuration(44.8)).toEqual('45s')
        expect(humanFriendlyDuration(45.2)).toEqual('45s')
    })
    it('returns correct value for 60 < t < 120', () => {
        expect(humanFriendlyDuration(90)).toEqual('1m 30s')
    })
    it('returns correct value for t > 120', () => {
        expect(humanFriendlyDuration(360)).toEqual('6m')
    })
    it('returns correct value for t >= 3600', () => {
        expect(humanFriendlyDuration(3600)).toEqual('1h')
        expect(humanFriendlyDuration(3601)).toEqual('1h 1s')
        expect(humanFriendlyDuration(3961)).toEqual('1h 6m 1s')
        expect(humanFriendlyDuration(3961.333)).toEqual('1h 6m 1s')
        expect(humanFriendlyDuration(3961.666)).toEqual('1h 6m 2s')
    })
    it('returns correct value for t >= 86400', () => {
        expect(humanFriendlyDuration(86400)).toEqual('1d')
        expect(humanFriendlyDuration(86400.12)).toEqual('1d')
    })
    it('truncates to specified # of units', () => {
        expect(humanFriendlyDuration(3961, 2)).toEqual('1h 6m')
        expect(humanFriendlyDuration(30, 2)).toEqual('30s') // no change
        expect(humanFriendlyDuration(30, 0)).toEqual('') // returns no units (useless)
    })
    it('returns an empty string for nullish inputs', () => {
        expect(humanFriendlyDuration('', 2)).toEqual('')
        expect(humanFriendlyDuration(null, 2)).toEqual('')
    })
})

describe('colonDelimitedDuration()', () => {
    it('returns correct value for <= 60', () => {
        expect(colonDelimitedDuration(59.9)).toEqual('00:00:59')
        expect(colonDelimitedDuration(60)).toEqual('00:01:00')
        expect(colonDelimitedDuration(45)).toEqual('00:00:45')
    })
    it('returns correct value for 60 < t < 120', () => {
        expect(colonDelimitedDuration(90)).toEqual('00:01:30')
    })
    it('returns correct value for t > 120', () => {
        expect(colonDelimitedDuration(360)).toEqual('00:06:00')
        expect(colonDelimitedDuration(360.3233)).toEqual('00:06:00')
        expect(colonDelimitedDuration(360.782)).toEqual('00:06:00')
    })
    it('returns correct value for t >= 3600', () => {
        expect(colonDelimitedDuration(3600)).toEqual('01:00:00')
        expect(colonDelimitedDuration(3601)).toEqual('01:00:01')
        expect(colonDelimitedDuration(3961)).toEqual('01:06:01')
    })
    it('returns correct value for t >= 86400', () => {
        expect(colonDelimitedDuration(86400)).toEqual('24:00:00')
        expect(colonDelimitedDuration(90000)).toEqual('25:00:00')
    })
    it('returns correct value for numUnits < 3', () => {
        expect(colonDelimitedDuration(86400, 2)).toEqual('1440:00')
        expect(colonDelimitedDuration(86400, 1)).toEqual('86400')
    })
    it('returns correct value for numUnits >= 4', () => {
        expect(colonDelimitedDuration(86400, 4)).toEqual('01:00:00:00')
        expect(colonDelimitedDuration(90000, 4)).toEqual('01:01:00:00')
        expect(colonDelimitedDuration(90061, 4)).toEqual('01:01:01:01')
        expect(colonDelimitedDuration(604800, 5)).toEqual('01:00:00:00:00')
        expect(colonDelimitedDuration(604800, 6)).toEqual('01:00:00:00:00')
        expect(colonDelimitedDuration(604800.222, 5)).toEqual('01:00:00:00:00')
        expect(colonDelimitedDuration(604800.999, 6)).toEqual('01:00:00:00:00')
    })
    it('returns an empty string for nullish inputs', () => {
        expect(colonDelimitedDuration('')).toEqual('')
        expect(colonDelimitedDuration(null)).toEqual('')
        expect(colonDelimitedDuration(undefined)).toEqual('')
    })
})

describe('areObjectValuesEmpty()', () => {
    it('returns correct value for objects with empty values', () => {
        expect(areObjectValuesEmpty({ a: '', b: null, c: undefined })).toEqual(true)
        expect(areObjectValuesEmpty({ a: undefined, b: undefined })).toEqual(true)
        expect(areObjectValuesEmpty({})).toEqual(true)
    })
    it('returns correct value for objects with at least one non-empty value', () => {
        expect(areObjectValuesEmpty({ a: '', b: null, c: 'hello' })).toEqual(false)
        expect(areObjectValuesEmpty({ a: true, b: 'hello' })).toEqual(false)
        expect(areObjectValuesEmpty('hello' as any)).toEqual(false)
        expect(areObjectValuesEmpty(null as any)).toEqual(false)
    })
})

describe('ensureStringIsNotBlank()', () => {
    it('handles unusual input', () => {
        expect(ensureStringIsNotBlank(null)).toEqual(null)
        expect(ensureStringIsNotBlank({} as any)).toEqual(null)
        expect(ensureStringIsNotBlank(undefined)).toEqual(null)
        expect(ensureStringIsNotBlank(true as any)).toEqual(null)
    })
    it('handles blank strings as expected', () => {
        expect(ensureStringIsNotBlank('')).toEqual(null)
        expect(ensureStringIsNotBlank('    ')).toEqual(null)
    })
    it('handles happy case', () => {
        expect(ensureStringIsNotBlank('happyboy')).toEqual('happyboy')
        expect(ensureStringIsNotBlank('  happy boy  ')).toEqual('  happy boy  ')
    })
})

describe('objectDiffShallow()', () => {
    it('obj1 + result = obj2', () => {
        expect(objectDiffShallow({ b: '4' }, { b: '3', a: '2' })).toStrictEqual({ b: '3', a: '2' })
        expect(objectDiffShallow({ b: '4', c: '12' }, { b: '3', a: '2' })).toStrictEqual({
            b: '3',
            a: '2',
            c: undefined,
        })
    })
})

describe('eventToName()', () => {
    const baseEvent = {
        elements: [],
        event: '',
        properties: {},
        person: {},
    }

    it('handles page events as expected', () => {
        expect(eventToDescription({ ...baseEvent, event: '$pageview', properties: { $pathname: '/hello' } })).toEqual(
            '/hello'
        )
        expect(eventToDescription({ ...baseEvent, event: '$pageleave', properties: { $pathname: '/bye' } })).toEqual(
            '/bye'
        )
    })

    it('handles no text autocapture as expected', () => {
        expect(
            eventToDescription({
                ...baseEvent,
                event: '$autocapture',
                properties: { $event_type: 'click' },
            })
        ).toEqual('clicked element')
    })

    it('handles long form autocapture as expected', () => {
        expect(
            eventToDescription({
                ...baseEvent,
                event: '$autocapture',
                properties: { $event_type: 'click' },
                elements: [{ tag_name: 'button', text: 'hello' } as ElementType],
            })
        ).toEqual('clicked button with text "hello"')
    })

    it('handles short form autocapture as expected', () => {
        expect(
            eventToDescription(
                {
                    ...baseEvent,
                    event: '$autocapture',
                    properties: { $event_type: 'click' },
                    elements: [{ tag_name: 'button', text: 'hello' } as ElementType],
                },
                true
            )
        ).toEqual('clicked "hello"')
    })

    it('handles unknown event/action', () => {
        expect(
            eventToDescription({
                ...baseEvent,
                event: 'custom event/action',
            })
        ).toEqual('custom event/action')
    })
})

describe('{floor|ceil}MsToClosestSecond()', () => {
    describe('ceil', () => {
        it('handles ms as expected', () => {
            expect(ceilMsToClosestSecond(10532)).toEqual(11000)
            expect(ceilMsToClosestSecond(1500)).toEqual(2000)
            expect(ceilMsToClosestSecond(500)).toEqual(1000)
            expect(ceilMsToClosestSecond(-10532)).toEqual(-10000)
            expect(ceilMsToClosestSecond(-1500)).toEqual(-1000)
            expect(ceilMsToClosestSecond(-500)).toEqual(-0)
        })
        it('handles whole seconds as expected', () => {
            expect(ceilMsToClosestSecond(0)).toEqual(0)
            expect(ceilMsToClosestSecond(1000)).toEqual(1000)
            expect(ceilMsToClosestSecond(-1000)).toEqual(-1000)
        })
    })

    describe('floor', () => {
        it('handles ms as expected', () => {
            expect(floorMsToClosestSecond(10532)).toEqual(10000)
            expect(floorMsToClosestSecond(1500)).toEqual(1000)
            expect(floorMsToClosestSecond(500)).toEqual(0)
            expect(floorMsToClosestSecond(-10532)).toEqual(-11000)
            expect(floorMsToClosestSecond(-1500)).toEqual(-2000)
            expect(floorMsToClosestSecond(-500)).toEqual(-1000)
        })
        it('handles whole seconds as expected', () => {
            expect(floorMsToClosestSecond(0)).toEqual(0)
            expect(floorMsToClosestSecond(1000)).toEqual(1000)
            expect(floorMsToClosestSecond(-1000)).toEqual(-1000)
        })
    })

    describe('choosing an operator for taxonomic filters', () => {
        const testCases = [
            { propertyType: PropertyType.DateTime, expected: dateTimeOperatorMap },
            { propertyType: PropertyType.String, expected: stringOperatorMap },
            { propertyType: PropertyType.Numeric, expected: numericOperatorMap },
            { propertyType: PropertyType.Boolean, expected: booleanOperatorMap },
            { propertyType: PropertyType.Duration, expected: durationOperatorMap },
            { propertyType: undefined, expected: genericOperatorMap },
        ]
        testCases.forEach((testcase) => {
            it(`correctly maps ${testcase.propertyType} to operator options`, () => {
                expect(chooseOperatorMap(testcase.propertyType)).toEqual(testcase.expected)
            })
        })
    })
})

describe('convertPropertyGroupToProperties()', () => {
    it('converts a single layer property group into an array of properties', () => {
        const propertyGroup = {
            type: FilterLogicalOperator.And,
            values: [
                { type: FilterLogicalOperator.And, values: [{ key: '$browser' }, { key: '$current_url' }] },
                { type: FilterLogicalOperator.And, values: [{ key: '$lib' }] },
            ],
        }
        expect(convertPropertyGroupToProperties(propertyGroup)).toEqual([
            { key: '$browser' },
            { key: '$current_url' },
            { key: '$lib' },
        ])
    })

    it('converts a deeply nested property group into an array of properties', () => {
        const propertyGroup = {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [{ type: FilterLogicalOperator.And, values: [{ key: '$lib' }] }],
                },
                { type: FilterLogicalOperator.And, values: [{ key: '$browser' }] },
            ],
        }
        expect(convertPropertyGroupToProperties(propertyGroup)).toEqual([{ key: '$lib' }, { key: '$browser' }])
    })
})

describe('convertPropertiesToPropertyGroup', () => {
    it('converts properties to one AND operator property group', () => {
        const properties = [{ key: '$lib' }, { key: '$browser' }, { key: '$current_url' }]
        expect(convertPropertiesToPropertyGroup(properties)).toEqual({
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [{ key: '$lib' }, { key: '$browser' }, { key: '$current_url' }],
                },
            ],
        })
    })

    it('converts properties to one AND operator property group', () => {
        expect(convertPropertiesToPropertyGroup(undefined)).toEqual({
            type: FilterLogicalOperator.And,
            values: [],
        })
    })
})

describe('calculateDays', () => {
    it('1 day to 1 day', () => {
        expect(calculateDays(1, TimeUnitType.Day)).toEqual(1)
    })
    it('1 week to 7 days', () => {
        expect(calculateDays(1, TimeUnitType.Week)).toEqual(7)
    })
    it('1 month to 30 days', () => {
        expect(calculateDays(1, TimeUnitType.Month)).toEqual(30)
    })
    it('1 year to 365 days', () => {
        expect(calculateDays(1, TimeUnitType.Year)).toEqual(365)
    })
})

describe('range', () => {
    it('creates simple range', () => {
        expect(range(4)).toEqual([0, 1, 2, 3])
    })

    it('creates offset range', () => {
        expect(range(1, 5)).toEqual([1, 2, 3, 4])
    })
})
