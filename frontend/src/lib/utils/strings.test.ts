import {
    capitalizeFirstLetter,
    endWithPunctation,
    ensureStringIsNotBlank,
    identifierToHuman,
    midEllipsis,
    pluralize,
    wordPluralize,
} from 'lib/utils/strings'

describe('strings utils', () => {
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
            expect(identifierToHuman('hog_function/transformation')).toEqual('Hog function transformation')
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

        it('returns falsy input unchanged without throwing', () => {
            expect(wordPluralize('')).toEqual('')
            expect(wordPluralize(null as unknown as string)).toEqual('')
            expect(wordPluralize(undefined as unknown as string)).toEqual('')
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
})
