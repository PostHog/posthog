import tk from 'timekeeper'

import { dayjs } from 'lib/dayjs'

import { ElementType, EventType, PropertyType, TimeUnitType } from '~/types'

import {
    areDatesValidForInterval,
    areObjectValuesEmpty,
    autoCaptureEventToDescription,
    average,
    booleanOperatorMap,
    calculateDays,
    capitalizeFirstLetter,
    ceilMsToClosestSecond,
    chooseOperatorMap,
    colonDelimitedDuration,
    compactNumber,
    dateFilterToText,
    dateMapping,
    dateStringToDayJs,
    dateTimeOperatorMap,
    durationOperatorMap,
    endWithPunctation,
    ensureStringIsNotBlank,
    eventToDescription,
    floorMsToClosestSecond,
    formatDateTimeRange,
    genericOperatorMap,
    getDefaultInterval,
    getFormattedLastWeekDate,
    getRelativeNextPath,
    hexToRGBA,
    humanFriendlyDuration,
    humanFriendlyLargeNumber,
    identifierToHuman,
    is12HoursOrLess,
    isExternalLink,
    isLessThan2Days,
    isURL,
    median,
    midEllipsis,
    numericOperatorMap,
    objectClean,
    objectCleanWithEmpty,
    objectDiffShallow,
    parseTagsFilter,
    pluralize,
    range,
    reverseColonDelimitedDuration,
    roundToDecimal,
    selectorOperatorMap,
    shortTimeZone,
    stringOperatorMap,
    toParams,
    wordPluralize,
} from './utils'

describe('lib/utils', () => {
    describe('toParams', () => {
        it('handles unusual input', () => {
            expect(toParams({})).toEqual('')
            expect(toParams([])).toEqual('')
            expect(toParams(undefined as any)).toEqual('')
            expect(toParams(null as any)).toEqual('')
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

    describe('midEllipsis()', () => {
        it('returns same string if short', () => {
            expect(midEllipsis('12', 10)).toEqual('12')
            expect(midEllipsis('1234567890', 10)).toEqual('1234567890')
        })

        it('formats string properly', () => {
            expect(midEllipsis('1234567890', 2)).toEqual('1…')
            expect(midEllipsis('1234567890', 4)).toEqual('12…0')
            expect(midEllipsis('1234567890', 8)).toEqual('1234…890')
            expect(midEllipsis('1234567890', 9)).toEqual('1234…7890')
            expect(midEllipsis('ZgZbZgD9Z4U2FsohDYAJ-hMdoxY7-oSdWwrEWtdBeM', 26)).toEqual('ZgZbZgD9Z4U2F…SdWwrEWtdBeM')
            expect(midEllipsis('ZgZbZgD9Z4U2FsohDYAJ-hMdoxY7-oSdWwrEWtdBeM', 25)).toEqual('ZgZbZgD9Z4U2…SdWwrEWtdBeM')
            expect(midEllipsis('ZgZbZgD9Z4U2FsohDYAJ-hMdoxY7-oSdWwrEWtdBeM', 24)).toEqual('ZgZbZgD9Z4U2…dWwrEWtdBeM')
        })
    })

    describe('isURL()', () => {
        it('recognizes URLs properly', () => {
            expect(isURL('https://www.posthog.com')).toEqual(true)
            expect(isURL('http://www.posthog.com')).toEqual(true)
            expect(isURL('http://www.posthog.com:8000/images')).toEqual(true)
            expect(isURL('http://localhost:8000/login?next=/insights')).toEqual(true)
            expect(isURL('http://localhost:8000/activity/explore?properties=%5B%5D')).toEqual(true)
            expect(isURL('https://apple.com/')).toEqual(true)
            expect(isURL('https://stripe.com')).toEqual(true)
            expect(isURL('https://spotify.com')).toEqual(true)
            expect(isURL('https://sevenapp.events/')).toEqual(true)
            expect(isURL('https://seven-stagingenv.web.app/')).toEqual(true)
            expect(isURL('https://salesforce.co.uk/')).toEqual(true)
            expect(isURL('https://valid.*.example.com')).toEqual(true)
            expect(isURL('https://*.valid.com')).toEqual(true)
        })

        it('recognizes non-URLs properly', () => {
            expect(isURL('1234567890')).toEqual(false)
            expect(isURL('www.posthog')).toEqual(false)
            expect(isURL('-.posthog')).toEqual(false)
            expect(isURL('posthog.3')).toEqual(false)
            expect(isURL(1)).toEqual(false)
            expect(isURL(true)).toEqual(false)
            expect(isURL(null)).toEqual(false)
            expect(isURL('')).toEqual(false)
            expect(isURL('  ')).toEqual(false)
            expect(
                isURL(
                    'https://client.rrrr.alpha.dev.foo.bar/9RvDy6gCmic_srrKs1db?sourceOrigin=rrrr&embedded={%22hostContext%22:%22landing%22,%22hostType%22:%22web%22,%22type%22:%22popsync%22}&share=1&wrapperUrl=https%3A%2F%2Fuat.rrrr.io%2F9RvDy6gCmicxyz&save=1&initialSearch={%22sites%22:%22google.com,gettyimages.com%22,%22safe%22:true,%22q%22:%22Perro%22}&opcid=4360f861-ffff-4444-9999-5257065a7dc3&waitForToken=1'
                )
            ).toEqual(false)
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
            expect(compactNumber(5001)).toEqual('5 K')
            expect(compactNumber(5312)).toEqual('5.31 K')
            expect(compactNumber(5392)).toEqual('5.39 K')
            expect(compactNumber(2833102)).toEqual('2.83 M')
            expect(compactNumber(8283310234)).toEqual('8.28 B')
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

    describe('wordPluralize()', () => {
        it('handles singular cases', () => {
            expect(wordPluralize('company')).toEqual('companies')
            expect(wordPluralize('person')).toEqual('people')
            expect(wordPluralize('bacterium')).toEqual('bacteria')
            expect(wordPluralize('word')).toEqual('words')
            expect(wordPluralize('child')).toEqual('children')
            expect(wordPluralize('knife')).toEqual('knives')
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
                expect(dateFilterToText('-1d', null, 'default')).toEqual('Last 1 day')
                expect(dateFilterToText('-1dStart', '-1dEnd', 'default')).toEqual('Yesterday')
                expect(dateFilterToText('-1mStart', '-1mEnd', 'default')).toEqual('Last month')
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
                // 2012-03-02T11:38:49.321Z
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
                expect(dateFilterToText('-1d', null, 'default', dateMapping, true)).toEqual('March 1 - March 2, 2012')
                expect(dateFilterToText('-1dStart', '-1dEnd', 'default', dateMapping, true)).toEqual('March 1, 2012')
                expect(dateFilterToText('-1mStart', '-1mEnd', 'default', dateMapping, true)).toEqual(
                    'February 1 - February 29, 2012'
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

    describe('dateStringToDayJs', () => {
        beforeEach(() => {
            tk.freeze(1330688329321) // randomly chosen time on the 22nd of February 2022
        })
        afterEach(() => {
            tk.reset()
        })

        it('handles various dates', () => {
            expect(dateStringToDayJs('2022-02-22')?.utc(true).toISOString()).toEqual('2022-02-22T00:00:00.000Z')
            expect(dateStringToDayJs('1999-12-31')?.utc(true).toISOString()).toEqual('1999-12-31T00:00:00.000Z')
        })

        it('handles various units', () => {
            expect(dateStringToDayJs('d')?.utc(true).toISOString()).toEqual('2012-03-02T00:00:00.000Z')
            expect(dateStringToDayJs('m')?.utc(true).toISOString()).toEqual('2012-03-02T00:00:00.000Z')
            expect(dateStringToDayJs('w')?.utc(true).toISOString()).toEqual('2012-03-02T00:00:00.000Z')
            expect(dateStringToDayJs('q')?.utc(true).toISOString()).toEqual('2012-03-02T00:00:00.000Z')
            expect(dateStringToDayJs('y')?.utc(true).toISOString()).toEqual('2012-03-02T00:00:00.000Z')
            expect(dateStringToDayJs('x')).toEqual(null)
        })

        it('handles pluses and minuses', () => {
            expect(dateStringToDayJs('d')?.utc(true).toISOString()).toEqual('2012-03-02T00:00:00.000Z')
            expect(dateStringToDayJs('+d')?.utc(true).toISOString()).toEqual('2012-03-02T00:00:00.000Z')
            expect(dateStringToDayJs('-d')?.utc(true).toISOString()).toEqual('2012-03-02T00:00:00.000Z')

            expect(dateStringToDayJs('1d')?.utc(true).toISOString()).toEqual('2012-03-03T00:00:00.000Z')
            expect(dateStringToDayJs('2d')?.utc(true).toISOString()).toEqual('2012-03-04T00:00:00.000Z')
            expect(dateStringToDayJs('3d')?.utc(true).toISOString()).toEqual('2012-03-05T00:00:00.000Z')
            expect(dateStringToDayJs('33d')?.utc(true).toISOString()).toEqual('2012-04-04T00:00:00.000Z')

            expect(dateStringToDayJs('+1d')?.utc(true).toISOString()).toEqual('2012-03-03T00:00:00.000Z')
            expect(dateStringToDayJs('+2d')?.utc(true).toISOString()).toEqual('2012-03-04T00:00:00.000Z')
            expect(dateStringToDayJs('+3d')?.utc(true).toISOString()).toEqual('2012-03-05T00:00:00.000Z')
            expect(dateStringToDayJs('+33d')?.utc(true).toISOString()).toEqual('2012-04-04T00:00:00.000Z')

            expect(dateStringToDayJs('-1d')?.utc(true).toISOString()).toEqual('2012-03-01T00:00:00.000Z')
            expect(dateStringToDayJs('-2d')?.utc(true).toISOString()).toEqual('2012-02-29T00:00:00.000Z')
            expect(dateStringToDayJs('-3d')?.utc(true).toISOString()).toEqual('2012-02-28T00:00:00.000Z')
            expect(dateStringToDayJs('-33d')?.utc(true).toISOString()).toEqual('2012-01-29T00:00:00.000Z')

            expect(dateStringToDayJs('-33m')?.utc(true).toISOString()).toEqual('2009-06-02T00:00:00.000Z')
            expect(dateStringToDayJs('-33w')?.utc(true).toISOString()).toEqual('2011-07-15T00:00:00.000Z')
            expect(dateStringToDayJs('-33q')?.utc(true).toISOString()).toEqual('2003-12-02T00:00:00.000Z')
            expect(dateStringToDayJs('-33y')?.utc(true).toISOString()).toEqual('1979-03-02T00:00:00.000Z')
        })

        it('handles various start/end values', () => {
            expect(dateStringToDayJs('dStart')?.utc(true).toISOString()).toEqual('2012-03-02T00:00:00.000Z')
            expect(dateStringToDayJs('dEnd')?.utc(true).toISOString()).toEqual('2012-03-02T23:59:59.999Z')
            expect(dateStringToDayJs('wStart')?.utc(true).toISOString()).toEqual('2012-02-26T00:00:00.000Z')
            expect(dateStringToDayJs('wEnd')?.utc(true).toISOString()).toEqual('2012-03-03T23:59:59.999Z')
            expect(dateStringToDayJs('mStart')?.utc(true).toISOString()).toEqual('2012-03-01T00:00:00.000Z')
            expect(dateStringToDayJs('mEnd')?.utc(true).toISOString()).toEqual('2012-03-31T23:59:59.999Z')
            expect(dateStringToDayJs('qStart')?.utc(true).toISOString()).toEqual('2012-01-01T00:00:00.000Z')
            expect(dateStringToDayJs('qEnd')?.utc(true).toISOString()).toEqual('2012-03-31T23:59:59.999Z')
            expect(dateStringToDayJs('yStart')?.utc(true).toISOString()).toEqual('2012-01-01T00:00:00.000Z')
            expect(dateStringToDayJs('yEnd')?.utc(true).toISOString()).toEqual('2012-12-31T23:59:59.999Z')
        })

        it('handles various start/end values with units', () => {
            expect(dateStringToDayJs('1dStart')?.utc(true).toISOString()).toEqual('2012-03-03T00:00:00.000Z')
            expect(dateStringToDayJs('1dEnd')?.utc(true).toISOString()).toEqual('2012-03-03T23:59:59.999Z')

            expect(dateStringToDayJs('-1wStart')?.utc(true).toISOString()).toEqual('2012-02-19T00:00:00.000Z')
            expect(dateStringToDayJs('-1wEnd')?.utc(true).toISOString()).toEqual('2012-02-25T23:59:59.999Z')

            expect(dateStringToDayJs('12mStart')?.utc(true).toISOString()).toEqual('2013-03-01T00:00:00.000Z')
            expect(dateStringToDayJs('12mEnd')?.utc(true).toISOString()).toEqual('2013-03-31T23:59:59.999Z')

            expect(dateStringToDayJs('-4qStart')?.utc(true).toISOString()).toEqual('2011-01-01T00:00:00.000Z')
            expect(dateStringToDayJs('-4qEnd')?.utc(true).toISOString()).toEqual('2011-03-31T23:59:59.999Z')

            expect(dateStringToDayJs('0yStart')?.utc(true).toISOString()).toEqual('2012-01-01T00:00:00.000Z')
            expect(dateStringToDayJs('0yEnd')?.utc(true).toISOString()).toEqual('2012-12-31T23:59:59.999Z')
        })
    })

    describe('getDefaultInterval', () => {
        it('should return days for last 7 days', () => {
            expect(getDefaultInterval('-7d', null)).toEqual('day')
        })

        it('should return hours for last 24 hours', () => {
            expect(getDefaultInterval('-24h', null)).toEqual('hour')
        })

        it('should return days for month to date', () => {
            expect(getDefaultInterval('mStart', null)).toEqual('day')
        })

        it('should return month for year to date', () => {
            expect(getDefaultInterval('yStart', null)).toEqual('month')
        })

        it('should return month for all time', () => {
            expect(getDefaultInterval('all', null)).toEqual('month')
        })

        it('should handle explicit dates 6 months apart', () => {
            expect(getDefaultInterval('2023-10-01', '2023-04-01')).toEqual('month')
        })
        it('should handle explicit dates a month apart', () => {
            expect(getDefaultInterval('2023-10-01', '2023-09-01')).toEqual('week')
        })
        it('should handle explicit dates a week apart', () => {
            expect(getDefaultInterval('2023-10-01', '2023-09-25')).toEqual('day')
        })
        it('should handle explicit dates a day apart', () => {
            expect(getDefaultInterval('2023-10-02', '2023-10-01')).toEqual('hour')
        })
        it('should handle explicit dates 12 hours apart', () => {
            expect(getDefaultInterval('2023-10-01T18:00:00', '2023-10-01T6:00:00')).toEqual('hour')
        })
    })

    describe('areDatesValidForInterval', () => {
        it('should require interval to be month for all time', () => {
            expect(areDatesValidForInterval('month', 'all', null)).toEqual(true)
            expect(areDatesValidForInterval('week', 'all', null)).toEqual(false)
            expect(areDatesValidForInterval('day', 'all', null)).toEqual(false)
            expect(areDatesValidForInterval('hour', 'all', null)).toEqual(false)
        })
        it('should return false if the dates are one interval apart', () => {
            expect(areDatesValidForInterval('day', '-24h', null)).toEqual(false)
            expect(areDatesValidForInterval('week', '-7d', null)).toEqual(false)
            expect(areDatesValidForInterval('day', '-1d', null)).toEqual(false)
        })
        it('should return true if the dates are two intervals apart', () => {
            expect(areDatesValidForInterval('day', '-48h', null)).toEqual(true)
            expect(areDatesValidForInterval('week', '-14d', null)).toEqual(true)
            expect(areDatesValidForInterval('day', '-2d', null)).toEqual(true)
        })
        it('should return false for hourly if over 2 weeks', () => {
            expect(areDatesValidForInterval('hour', '-15d', null)).toEqual(false)
        })
        it('should support explicit dates', () => {
            expect(areDatesValidForInterval('month', '2023-08-01', '2023-11-01')).toEqual(true)
            expect(areDatesValidForInterval('week', '2023-10-01', '2023-11-01')).toEqual(true)
            expect(areDatesValidForInterval('day', '2023-10-16', '2023-11-01')).toEqual(true)
            expect(areDatesValidForInterval('hour', '2023-11-01T12', '2023-11-01T18')).toEqual(true)
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

    describe('humanFriendlyLargeNumber()', () => {
        it('returns the correct string', () => {
            expect(humanFriendlyLargeNumber(1.234)).toEqual('1.23')
            expect(humanFriendlyLargeNumber(12.34)).toEqual('12.3')
            expect(humanFriendlyLargeNumber(123.4)).toEqual('123')
            expect(humanFriendlyLargeNumber(1234)).toEqual('1.23K')
            expect(humanFriendlyLargeNumber(12345)).toEqual('12.3K')
            expect(humanFriendlyLargeNumber(123456)).toEqual('123K')
            expect(humanFriendlyLargeNumber(1234567)).toEqual('1.23M')
            expect(humanFriendlyLargeNumber(-1234567)).toEqual('-1.23M')
            expect(humanFriendlyLargeNumber(-1)).toEqual('-1')
            expect(humanFriendlyLargeNumber(-0.1)).toEqual('-0.1')
            expect(humanFriendlyLargeNumber(0)).toEqual('0')
            expect(humanFriendlyLargeNumber(NaN)).toEqual('NaN')
            expect(humanFriendlyLargeNumber(Infinity)).toEqual('inf')
            expect(humanFriendlyLargeNumber(-Infinity)).toEqual('-inf')
        })
    })
    describe('humanFriendlyDuration()', () => {
        it('returns correct value for 0 <= t < 1', () => {
            expect(humanFriendlyDuration(0)).toEqual('0s')
            expect(humanFriendlyDuration(0.001)).toEqual('1ms')
            expect(humanFriendlyDuration(0.02)).toEqual('20ms')
            expect(humanFriendlyDuration(0.3)).toEqual('300ms')
            expect(humanFriendlyDuration(0.999)).toEqual('999ms')
        })

        it('returns correct value for 1 < t <= 60', () => {
            expect(humanFriendlyDuration(60)).toEqual('1m')
            expect(humanFriendlyDuration(45)).toEqual('45s')
            expect(humanFriendlyDuration(44.8)).toEqual('45s')
            expect(humanFriendlyDuration(45.2)).toEqual('45s')
            expect(humanFriendlyDuration(45.2, { secondsFixed: 1 })).toEqual('45.2s')
            expect(humanFriendlyDuration(1.23)).toEqual('1s')
            expect(humanFriendlyDuration(1.23, { secondsPrecision: 3 })).toEqual('1.23s')
            expect(humanFriendlyDuration(1, { secondsPrecision: 3 })).toEqual('1s')
            expect(humanFriendlyDuration(1, { secondsFixed: 1 })).toEqual('1s')
            expect(humanFriendlyDuration(1)).toEqual('1s')
        })
        it('returns correct value for 60 < t < 120', () => {
            expect(humanFriendlyDuration(119.6)).toEqual('1m 59s')
            expect(humanFriendlyDuration(90)).toEqual('1m 30s')
        })
        it('returns correct value for t > 120', () => {
            expect(humanFriendlyDuration(360)).toEqual('6m')
        })
        it('returns correct value for t >= 3600', () => {
            expect(humanFriendlyDuration(3600)).toEqual('1h')
            expect(humanFriendlyDuration(3601)).toEqual('1h 1s')
            expect(humanFriendlyDuration(3961)).toEqual('1h 6m 1s')
            expect(humanFriendlyDuration(3961.333)).toEqual('1h 6m 1s')
            expect(humanFriendlyDuration(3961.666)).toEqual('1h 6m 1s')
        })
        it('returns correct value for t >= 86400', () => {
            expect(humanFriendlyDuration(86400)).toEqual('1d')
            expect(humanFriendlyDuration(86400.12)).toEqual('1d')
        })
        it('truncates to specified # of units', () => {
            expect(humanFriendlyDuration(3961, { maxUnits: 2 })).toEqual('1h 6m')
            expect(humanFriendlyDuration(30, { maxUnits: 2 })).toEqual('30s') // no change
            expect(humanFriendlyDuration(30, { maxUnits: 0 })).toEqual('') // returns no units (useless)
        })
        it('returns an empty string for nullish inputs', () => {
            expect(humanFriendlyDuration('', { maxUnits: 2 })).toEqual('')
            expect(humanFriendlyDuration(null, { maxUnits: 2 })).toEqual('')
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
        it('returns the smallest possible for numUnits = null', () => {
            expect(colonDelimitedDuration(59, null)).toEqual('00:59')
            expect(colonDelimitedDuration(3599, null)).toEqual('59:59')
            expect(colonDelimitedDuration(3600, null)).toEqual('01:00:00')
        })
        it('returns an empty string for nullish inputs', () => {
            expect(colonDelimitedDuration('')).toEqual('')
            expect(colonDelimitedDuration(null)).toEqual('')
            expect(colonDelimitedDuration(undefined)).toEqual('')
        })
    })

    describe('reverseColonDelimitedDuration()', () => {
        it('returns correct value', () => {
            expect(reverseColonDelimitedDuration('59')).toEqual(59)
            expect(reverseColonDelimitedDuration('59:59')).toEqual(3599)
            expect(reverseColonDelimitedDuration('23:59:59')).toEqual(86399)
        })
        it('returns an null for bad values', () => {
            expect(reverseColonDelimitedDuration('1232123')).toEqual(null)
            expect(reverseColonDelimitedDuration('AA:AA:AA')).toEqual(null)
            expect(reverseColonDelimitedDuration(undefined)).toEqual(null)
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

    describe('objectClean()', () => {
        it('removes undefined values', () => {
            expect(objectClean({ a: 1, b: 'b', c: null, d: {}, e: [], f: undefined })).toStrictEqual({
                a: 1,
                b: 'b',
                c: null,
                d: {},
                e: [],
            })
        })
    })

    describe('objectCleanWithEmpty()', () => {
        it('removes undefined and empty values', () => {
            expect(
                objectCleanWithEmpty({ a: 1, b: 'b', c: null, d: {}, e: [], f: undefined, g: { x: 1 }, h: [1] })
            ).toStrictEqual({
                a: 1,
                b: 'b',
                c: null,
                g: { x: 1 },
                h: [1],
            })
        })
    })

    describe('eventToName()', () => {
        const baseEvent = {
            elements: [],
            event: '',
            properties: {},
            person: {},
        } as any as EventType

        it('handles page events as expected', () => {
            expect(
                eventToDescription({ ...baseEvent, event: '$pageview', properties: { $pathname: '/hello' } })
            ).toEqual('/hello')
            expect(
                eventToDescription({ ...baseEvent, event: '$pageleave', properties: { $pathname: '/bye' } })
            ).toEqual('/bye')
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

    describe('autoCaptureEventToDescription()', () => {
        const baseEvent = {
            elements: [],
            event: '$autocapture',
            properties: { $event_type: 'click' },
            person: {},
        } as any as EventType

        it('handles regular text by adding quotes', () => {
            expect(
                autoCaptureEventToDescription({
                    ...baseEvent,
                    properties: {
                        ...baseEvent.properties,
                        $el_text: 'Analyzing Characters with',
                    },
                })
            ).toEqual('clicked element with text "Analyzing Characters with"')
        })

        it('prioritizes $el_text from properties over text in elements array', () => {
            expect(
                autoCaptureEventToDescription({
                    ...baseEvent,
                    properties: {
                        ...baseEvent.properties,
                        $el_text: 'Text from properties',
                    },
                    elements: [{ tag_name: 'button', text: 'Text from elements' } as ElementType],
                })
            ).toEqual('clicked button with text "Text from properties"')
        })

        it('handles text with double quotes without adding additional quotes', () => {
            expect(
                autoCaptureEventToDescription({
                    ...baseEvent,
                    properties: {
                        ...baseEvent.properties,
                        $el_text: 'Unit Skills Assessment 1: "',
                    },
                })
            ).toEqual('clicked element with text "Unit Skills Assessment 1: ""')
        })

        it('handles text with single quotes without adding additional quotes', () => {
            expect(
                autoCaptureEventToDescription({
                    ...baseEvent,
                    properties: {
                        ...baseEvent.properties,
                        $el_text: "Reading Lesson: '",
                    },
                })
            ).toEqual('clicked element with text "Reading Lesson: \'"')
        })

        it('handles longer text with single quotes without adding additional quotes', () => {
            expect(
                autoCaptureEventToDescription({
                    ...baseEvent,
                    properties: {
                        ...baseEvent.properties,
                        $el_text: "A Sense of Wonder: An Introduction to Science Fiction'",
                    },
                })
            ).toEqual('clicked element with text "A Sense of Wonder: An Introduction to Science Fiction\'"')
        })

        it('handles text in elements array', () => {
            expect(
                autoCaptureEventToDescription({
                    ...baseEvent,
                    elements: [{ tag_name: 'button', text: 'hello world' } as ElementType],
                })
            ).toEqual('clicked button with text "hello world"')
        })

        it('handles text with quotes in elements array', () => {
            expect(
                autoCaptureEventToDescription({
                    ...baseEvent,
                    elements: [{ tag_name: 'button', text: 'hello "world"' } as ElementType],
                })
            ).toEqual('clicked button with text "hello "world""')
        })

        it('handles aria-label attributes', () => {
            expect(
                autoCaptureEventToDescription({
                    ...baseEvent,
                    elements: [
                        {
                            tag_name: 'button',
                            attributes: { 'attr__aria-label': 'Close dialog' },
                        } as ElementType,
                    ],
                })
            ).toEqual('clicked button with aria label "Close dialog"')
        })

        it('handles aria-label attributes with quotes', () => {
            expect(
                autoCaptureEventToDescription({
                    ...baseEvent,
                    elements: [
                        {
                            tag_name: 'button',
                            attributes: { 'attr__aria-label': 'Close "main" dialog' },
                        } as ElementType,
                    ],
                })
            ).toEqual('clicked button with aria label "Close "main" dialog"')
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
                { propertyType: PropertyType.Selector, expected: selectorOperatorMap },
                { propertyType: undefined, expected: genericOperatorMap },
            ]
            testCases.forEach((testcase) => {
                it(`correctly maps ${testcase.propertyType} to operator options`, () => {
                    expect(chooseOperatorMap(testcase.propertyType)).toEqual(testcase.expected)
                })
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

    describe('time ranges', () => {
        it('is less than or equal to 12 hours', () => {
            expect(is12HoursOrLess('-0h')).toBeTruthy()
            expect(is12HoursOrLess('-1h')).toBeTruthy()
            expect(is12HoursOrLess('-12h')).toBeTruthy()
            expect(is12HoursOrLess('-13h')).toBeFalsy()

            expect(is12HoursOrLess('-24h')).toBeFalsy()
            expect(is12HoursOrLess('-30h')).toBeFalsy()
            expect(is12HoursOrLess('-47h')).toBeFalsy()
            expect(is12HoursOrLess('-111h')).toBeFalsy()

            expect(is12HoursOrLess('-1.123h')).toBeFalsy()
            expect(is12HoursOrLess('1.123h')).toBeFalsy()
            expect(is12HoursOrLess('-ab1-13h')).toBeFalsy()
            expect(is12HoursOrLess('-1d')).toBeFalsy()
            expect(is12HoursOrLess('-1w')).toBeFalsy()
            expect(is12HoursOrLess('-1h-2h')).toBeFalsy()
        })

        it('is less than 2 days', () => {
            expect(isLessThan2Days('-0h')).toBeTruthy()
            expect(isLessThan2Days('-1h')).toBeTruthy()
            expect(isLessThan2Days('-12h')).toBeTruthy()
            expect(isLessThan2Days('-24h')).toBeTruthy()
            expect(isLessThan2Days('-30h')).toBeTruthy()
            expect(isLessThan2Days('-47h')).toBeTruthy()

            expect(isLessThan2Days('-48h')).toBeFalsy()
            expect(isLessThan2Days('-49h')).toBeFalsy()
            expect(isLessThan2Days('0h')).toBeFalsy()
            expect(isLessThan2Days('1h')).toBeFalsy()
            expect(isLessThan2Days('48h')).toBeFalsy()
            expect(isLessThan2Days('-13.123h')).toBeFalsy()
            expect(isLessThan2Days('13.123h')).toBeFalsy()
            expect(isLessThan2Days('-ab1-13h')).toBeFalsy()
            expect(isLessThan2Days('-1d-1h')).toBeFalsy()
        })
    })

    test('shortTimezone', () => {
        expect(shortTimeZone('UTC')).toEqual('UTC')
        // All timezones below don't observe DST for simplicity
        expect(shortTimeZone('America/Phoenix')).toEqual('MST')
        expect(shortTimeZone('Europe/Moscow')).toEqual('UTC+3')
        expect(shortTimeZone('Asia/Tokyo')).toEqual('UTC+9')
    })

    describe('getRelativeNextPath', () => {
        const location = {
            origin: 'https://us.posthog.com',
            protocol: 'https:',
            host: 'us.posthog.com',
            hostname: 'us.posthog.com',
            href: 'https://us.posthog.com/',
        } as Location

        it('returns relative path for same-origin absolute URL', () => {
            expect(getRelativeNextPath('https://us.posthog.com/test', location)).toBe('/test')
        })

        it('returns relative path for same-origin absolute URL with query and hash', () => {
            expect(getRelativeNextPath('https://us.posthog.com/test?foo=bar#baz', location)).toBe('/test?foo=bar#baz')
        })

        it('returns relative path for encoded same-origin absolute URL', () => {
            expect(getRelativeNextPath('https%3A%2F%2Fus.posthog.com%2Ftest', location)).toBe('/test')
        })

        it('returns relative path for root-relative path', () => {
            expect(getRelativeNextPath('/test', location)).toBe('/test')
        })

        it('returns relative path for root-relative path with query and hash', () => {
            expect(getRelativeNextPath('/test?foo=bar#baz', location)).toBe('/test?foo=bar#baz')
        })

        it('returns null for external absolute URL', () => {
            expect(getRelativeNextPath('https://evil.com/test', location)).toBeNull()
        })

        it('returns null for encoded external absolute URL', () => {
            expect(getRelativeNextPath('https%3A%2F%2Fevil.com%2Ftest', location)).toBeNull()
        })

        it('returns null for protocol-relative external URL', () => {
            expect(getRelativeNextPath('//evil.com/test', location)).toBeNull()
        })

        it('returns null for empty string', () => {
            expect(getRelativeNextPath('', location)).toBeNull()
        })

        it('returns null for malformed URL', () => {
            expect(getRelativeNextPath('http://', location)).toBeNull()
            expect(getRelativeNextPath('%%%%', location)).toBeNull()
        })

        it('returns null for non-string input', () => {
            expect(getRelativeNextPath(null, location)).toBeNull()
            expect(getRelativeNextPath(undefined, location)).toBeNull()
        })

        it('returns relative path for encoded root-relative path', () => {
            expect(getRelativeNextPath('%2Ftest%2Ffoo%3Fbar%3Dbaz%23hash', location)).toBe('/test/foo?bar=baz#hash')
        })

        it('returns null for encoded protocol-relative URL', () => {
            expect(getRelativeNextPath('%2F%2Fevil.com%2Ftest', location)).toBeNull()
        })
    })

    describe('parseTagsFilter()', () => {
        describe('array input', () => {
            it('handles string arrays', () => {
                expect(parseTagsFilter(['tag1', 'tag2', 'tag3'])).toEqual(['tag1', 'tag2', 'tag3'])
            })

            it('handles mixed type arrays', () => {
                expect(parseTagsFilter(['tag1', 123, true, null, undefined])).toEqual([
                    'tag1',
                    '123',
                    'true',
                    'null',
                    'undefined',
                ])
            })

            it('filters out empty values', () => {
                expect(parseTagsFilter(['tag1', '', 'tag2', null, 'tag3'])).toEqual(['tag1', 'tag2', 'null', 'tag3'])
            })

            it('handles empty array', () => {
                expect(parseTagsFilter([])).toEqual([])
            })
        })

        describe('JSON string input', () => {
            it('parses valid JSON arrays', () => {
                expect(parseTagsFilter('["tag1", "tag2", "tag3"]')).toEqual(['tag1', 'tag2', 'tag3'])
            })

            it('parses JSON arrays with mixed types', () => {
                expect(parseTagsFilter('["tag1", 123, true]')).toEqual(['tag1', '123', 'true'])
            })

            it('filters out empty values from JSON', () => {
                expect(parseTagsFilter('["tag1", "", "tag2", null, "tag3"]')).toEqual(['tag1', 'tag2', 'null', 'tag3'])
            })

            it('handles empty JSON array', () => {
                expect(parseTagsFilter('[]')).toEqual([])
            })

            it('handles malformed JSON gracefully', () => {
                expect(parseTagsFilter('["tag1", "tag2"')).toEqual(['["tag1"', '"tag2"'])
            })

            it('handles invalid JSON syntax', () => {
                expect(parseTagsFilter('{invalid json}')).toEqual(['{invalid json}'])
            })

            it('handles JSON that is not an array', () => {
                expect(parseTagsFilter('{"not": "an array"}')).toEqual(['{"not": "an array"}'])
            })

            it('handles JSON with trailing comma', () => {
                expect(parseTagsFilter('["tag1", "tag2",]')).toEqual(['["tag1"', '"tag2"', ']'])
            })
        })

        describe('comma-separated string input', () => {
            it('parses simple comma-separated values', () => {
                expect(parseTagsFilter('tag1,tag2,tag3')).toEqual(['tag1', 'tag2', 'tag3'])
            })

            it('trims whitespace from values', () => {
                expect(parseTagsFilter(' tag1 , tag2 , tag3 ')).toEqual(['tag1', 'tag2', 'tag3'])
            })

            it('filters out empty values', () => {
                expect(parseTagsFilter('tag1,,tag2, ,tag3')).toEqual(['tag1', 'tag2', 'tag3'])
            })

            it('handles single value', () => {
                expect(parseTagsFilter('tag1')).toEqual(['tag1'])
            })

            it('handles empty string', () => {
                expect(parseTagsFilter('')).toEqual([])
            })

            it('handles string with only whitespace', () => {
                expect(parseTagsFilter('   ')).toEqual([])
            })

            it('handles string with only commas', () => {
                expect(parseTagsFilter(',,')).toEqual([])
            })

            it('handles string with commas and whitespace', () => {
                expect(parseTagsFilter(' , , ')).toEqual([])
            })
        })

        describe('edge cases and invalid input', () => {
            it('returns undefined for null input', () => {
                expect(parseTagsFilter(null)).toBeUndefined()
            })

            it('returns undefined for undefined input', () => {
                expect(parseTagsFilter(undefined)).toBeUndefined()
            })

            it('returns undefined for number input', () => {
                expect(parseTagsFilter(123)).toBeUndefined()
            })

            it('returns undefined for boolean input', () => {
                expect(parseTagsFilter(true)).toBeUndefined()
                expect(parseTagsFilter(false)).toBeUndefined()
            })

            it('returns undefined for object input', () => {
                expect(parseTagsFilter({})).toBeUndefined()
                expect(parseTagsFilter({ tags: ['tag1'] })).toBeUndefined()
            })

            it('handles special characters in tags', () => {
                expect(parseTagsFilter('tag-with-dash,tag_with_underscore,tag.with.dots')).toEqual([
                    'tag-with-dash',
                    'tag_with_underscore',
                    'tag.with.dots',
                ])
            })

            it('handles unicode characters', () => {
                expect(parseTagsFilter('标签1,🏷️,тег')).toEqual(['标签1', '🏷️', 'тег'])
            })

            it('handles very long strings', () => {
                const longTag = 'a'.repeat(1000)
                expect(parseTagsFilter(longTag)).toEqual([longTag])
            })

            it('handles strings with newlines and tabs', () => {
                expect(parseTagsFilter('tag1\ntag2\ttag3')).toEqual(['tag1\ntag2\ttag3'])
            })
        })
    })

    describe('formatDateTimeRange()', () => {
        beforeEach(() => {
            tk.freeze(new Date('2025-03-15T12:00:00.000Z'))
        })
        afterEach(() => {
            tk.reset()
        })

        it('formats range in different years with full details', () => {
            const from = dayjs('2024-12-31T14:30:45')
            const to = dayjs('2025-01-01T16:45:30')
            expect(formatDateTimeRange(from, to)).toEqual('December 31, 2024 14:30:45 - January 1, 2025 16:45:30')
        })

        it('formats range in same year but different days', () => {
            const from = dayjs('2024-06-15T09:00:00')
            const to = dayjs('2024-06-20T17:30:00')
            expect(formatDateTimeRange(from, to)).toEqual('June 15, 2024 09:00 - June 20, 17:30')
        })

        it('hides time if both times are midnight', () => {
            const from = dayjs('2024-06-15T00:00:00')
            const to = dayjs('2024-06-20T00:00:00')
            expect(formatDateTimeRange(from, to)).toEqual('June 15, 2024  - June 20')
        })

        it('formats range in same year as current year', () => {
            const from = dayjs('2025-01-10T10:15:00')
            const to = dayjs('2025-02-05T14:20:00')
            expect(formatDateTimeRange(from, to)).toEqual('January 10, 10:15 - February 5, 14:20')
        })

        it('formats range on same day in different year', () => {
            const from = dayjs('2024-08-10T09:30:00')
            const to = dayjs('2024-08-10T18:45:00')
            expect(formatDateTimeRange(from, to)).toEqual('August 10, 2024 09:30 - 18:45')
        })

        it('formats range on same day in current year', () => {
            const from = dayjs('2025-03-15T08:00:00')
            const to = dayjs('2025-03-15T20:00:00')
            expect(formatDateTimeRange(from, to)).toEqual('08:00 - 20:00')
        })

        it('removes seconds when both times have zero seconds on same day', () => {
            const from = dayjs('2025-03-15T10:30:00')
            const to = dayjs('2025-03-15T14:45:00')
            expect(formatDateTimeRange(from, to)).toEqual('10:30 - 14:45')
        })

        it('includes seconds when start time has non-zero seconds', () => {
            const from = dayjs('2025-03-15T10:30:15')
            const to = dayjs('2025-03-15T14:45:00')
            expect(formatDateTimeRange(from, to)).toEqual('10:30:15 - 14:45:00')
        })

        it('includes seconds when end time has non-zero seconds', () => {
            const from = dayjs('2025-03-15T10:30:00')
            const to = dayjs('2025-03-15T14:45:30')
            expect(formatDateTimeRange(from, to)).toEqual('10:30:00 - 14:45:30')
        })

        it('includes seconds when both times have non-zero seconds', () => {
            const from = dayjs('2025-03-15T10:30:15')
            const to = dayjs('2025-03-15T14:45:30')
            expect(formatDateTimeRange(from, to)).toEqual('10:30:15 - 14:45:30')
        })

        it('handles range spanning different days in current year', () => {
            const from = dayjs('2025-03-14T22:00:00')
            const to = dayjs('2025-03-16T02:00:00')
            expect(formatDateTimeRange(from, to)).toEqual('March 14, 22:00 - March 16, 02:00')
        })

        it('handles very short time ranges on same day', () => {
            const from = dayjs('2025-03-15T12:00:00')
            const to = dayjs('2025-03-15T12:01:00')
            expect(formatDateTimeRange(from, to)).toEqual('12:00 - 12:01')
        })
    })
})
