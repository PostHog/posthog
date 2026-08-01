import { suggestEmailDomain } from 'lib/utils/emailDomainSuggestion'

describe('suggestEmailDomain', () => {
    it.each([
        ['user@gmial.com', 'user@gmail.com'],
        ['user@gmail.con', 'user@gmail.com'],
        ['user@yaho.com', 'user@yahoo.com'],
        ['user@hotmial.com', 'user@hotmail.com'],
        ['user@outllok.com', 'user@outlook.com'],
    ])('suggests a fix for a known-provider typo: %s -> %s', (input, expected) => {
        expect(suggestEmailDomain(input)).toEqual(expected)
    })

    it.each([
        ['user@theaccessgroup.com5', 'user@theaccessgroup.com'],
        ['user@example.cmo', 'user@example.com'],
        ['user@example.ogr', 'user@example.org'],
    ])('suggests a fix for a TLD typo on any domain: %s -> %s', (input, expected) => {
        expect(suggestEmailDomain(input)).toEqual(expected)
    })

    it.each([
        ['user@gmail.com', 'exact match to a known provider'],
        ['user@theaccessgroup.com', 'unrecognized but well-formed company domain'],
        ['user@company.io', 'unrecognized domain with a common TLD'],
        ['not-an-email', 'no @ in the string'],
        ['user@', 'nothing after the @'],
    ])('returns null for %s (%s)', (input) => {
        expect(suggestEmailDomain(input)).toBeNull()
    })
})
