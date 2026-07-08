import {
    getRelativeNextPath,
    isExternalLink,
    isURL,
    parseNumericArrayFilter,
    parseTagsFilter,
    toParams,
    tryDecodeURIComponent,
} from 'lib/utils/url'

describe('url utils', () => {
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

        it('does not throw when a nested object value is a bigint', () => {
            // Property filter values may be bigints (see PropertyFilterBaseValue), which crashed
            // toParams with "Do not know how to serialize a BigInt" via JSON.stringify
            const filters = { properties: [{ key: 'user_id', value: BigInt('9007199254740993') }] }
            expect(() => toParams({ filters })).not.toThrow()
            expect(toParams({ filters })).toContain('9007199254740993')
        })
    })

    describe('tryDecodeURIComponent', () => {
        it('decodes valid percent-encoded input', () => {
            expect(tryDecodeURIComponent('foo%20bar')).toEqual('foo bar')
        })

        it.each(['50%off', 'foo%bar', '%', '%E0%A4%A'])(
            'returns the raw value on malformed encoding (%s)',
            (raw) => {
                // decodeURIComponent throws URIError here; the fallback keeps the person scene from crashing
                expect(tryDecodeURIComponent(raw)).toEqual(raw)
            }
        )
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

        it('rejects dangerous protocols (XSS prevention)', () => {
            expect(isURL('javascript:alert(1)')).toEqual(false)
            expect(isURL('javascript:alert(document.cookie)')).toEqual(false)
            expect(isURL('JAVASCRIPT:alert(1)')).toEqual(false)
            expect(isURL('data:text/html,<script>alert(1)</script>')).toEqual(false)
            expect(isURL('vbscript:msgbox(1)')).toEqual(false)
            expect(isURL('file:///etc/passwd')).toEqual(false)
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

        it.each([
            ['/\\evil.com/path', '/-then-backslash'],
            ['/\\\\evil.com/path', '/-then-two-backslashes'],
            ['%2F%5Cevil.com%2Fpath', 'encoded /-then-backslash'],
        ])('returns null for backslash external bypass (%s — %s)', (input) => {
            // Browsers normalize backslashes in special-scheme URLs per WHATWG, so /\\evil.com
            // resolves to //evil.com and escapes the origin.
            expect(getRelativeNextPath(input, location)).toBeNull()
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

    describe('parseNumericArrayFilter()', () => {
        it('handles numeric arrays', () => {
            expect(parseNumericArrayFilter([1, 2, 3])).toEqual([1, 2, 3])
        })

        it('parses a JSON-encoded list', () => {
            expect(parseNumericArrayFilter('[1,2]')).toEqual([1, 2])
        })

        it('parses a comma-separated string', () => {
            expect(parseNumericArrayFilter('1,2')).toEqual([1, 2])
        })

        it('handles a single number', () => {
            expect(parseNumericArrayFilter(5)).toEqual([5])
        })

        it('returns undefined for malformed JSON rather than half-applying it', () => {
            expect(parseNumericArrayFilter('[5')).toBeUndefined()
        })

        it('returns undefined for a non-numeric string', () => {
            expect(parseNumericArrayFilter('abc')).toBeUndefined()
        })

        it('drops non-numeric entries from a comma-separated string', () => {
            expect(parseNumericArrayFilter('1,abc,3')).toEqual([1, 3])
        })

        it('returns undefined for empty string', () => {
            expect(parseNumericArrayFilter('')).toBeUndefined()
        })

        it('returns undefined for null and undefined', () => {
            expect(parseNumericArrayFilter(null)).toBeUndefined()
            expect(parseNumericArrayFilter(undefined)).toBeUndefined()
        })
    })
})
