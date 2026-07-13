import { PathCleaningFilter, PropertyOperator } from '~/types'

import { buildPageUrlOptions, cleanPageURLForDisplay, createPageReportsFilters } from './pageReportsLogic'

describe('createPageReportsFilters', () => {
    const hostFilters = (
        filters: ReturnType<typeof createPageReportsFilters>
    ): ReturnType<typeof createPageReportsFilters> => filters.filter((filter) => filter.key === '$host')

    const filterFor = (
        filters: ReturnType<typeof createPageReportsFilters>,
        key: string
    ): ReturnType<typeof createPageReportsFilters>[number] | undefined => filters.find((filter) => filter.key === key)

    test.each([
        {
            name: 'full URL with no selected host keeps the URL host and pathname',
            url: 'https://posthog.com/pricing',
            selectedHost: null,
            expectedHostValues: ['posthog.com'],
            expectKeys: ['$host', '$pathname'],
        },
        {
            name: 'selected host overrides the URL host without duplicating $host',
            url: 'https://posthog.com/pricing',
            selectedHost: 'eu.posthog.com',
            expectedHostValues: ['eu.posthog.com'],
            expectKeys: ['$host', '$pathname'],
        },
        {
            name: 'unparseable URL with a selected host appends the host filter to the fallback',
            url: 'not a url',
            selectedHost: 'posthog.com',
            expectedHostValues: ['posthog.com'],
            expectKeys: ['$current_url', '$host'],
        },
        {
            name: 'unparseable URL with no selected host adds no host filter',
            url: 'not a url',
            selectedHost: null,
            expectedHostValues: [],
            expectKeys: ['$current_url'],
        },
    ])('$name', ({ url, selectedHost, expectedHostValues, expectKeys }) => {
        const filters = createPageReportsFilters(url, true, selectedHost)

        expect(hostFilters(filters).map((filter) => filter.value)).toEqual(expectedHostValues)
        expect(filters.map((filter) => filter.key).sort()).toEqual([...expectKeys].sort())
    })

    // kea-router JSON-parses query params, so ?pageURL=123 arrives (and gets persisted) as a number
    test.each([123, true, null])('non-string page URL %p does not crash the filter builder', (url) => {
        expect(() => createPageReportsFilters(url as unknown as string, true, null)).not.toThrow()
    })

    test.each([
        {
            name: 'cleaning off keeps the pathname an exact match',
            url: 'https://posthog.com/pricing',
            selectedHost: null,
            isPathCleaningEnabled: false,
            expectedPathnameOperator: PropertyOperator.Exact,
            expectedPathnameValue: '/pricing',
            expectedHostValue: 'posthog.com',
        },
        {
            name: 'cleaning on switches the pathname to a cleaned-path match',
            url: 'https://posthog.com/pricing',
            selectedHost: null,
            isPathCleaningEnabled: true,
            expectedPathnameOperator: PropertyOperator.IsCleanedPathExact,
            expectedPathnameValue: '/pricing',
            expectedHostValue: 'posthog.com',
        },
        {
            name: 'cleaning on decodes the alias so it survives URL parsing',
            url: 'hedgebox.net/files/<id>/',
            selectedHost: null,
            isPathCleaningEnabled: true,
            expectedPathnameOperator: PropertyOperator.IsCleanedPathExact,
            expectedPathnameValue: '/files/<id>/',
            expectedHostValue: 'hedgebox.net',
        },
        {
            name: 'cleaning on with a selected host cleans the pathname but leaves the host exact',
            url: 'https://posthog.com/pricing',
            selectedHost: 'eu.posthog.com',
            isPathCleaningEnabled: true,
            expectedPathnameOperator: PropertyOperator.IsCleanedPathExact,
            expectedPathnameValue: '/pricing',
            expectedHostValue: 'eu.posthog.com',
        },
    ])(
        '$name',
        ({
            url,
            selectedHost,
            isPathCleaningEnabled,
            expectedPathnameOperator,
            expectedPathnameValue,
            expectedHostValue,
        }) => {
            const filters = createPageReportsFilters(url, true, selectedHost, isPathCleaningEnabled)

            const pathnameFilter = filterFor(filters, '$pathname')
            expect(pathnameFilter?.operator).toEqual(expectedPathnameOperator)
            expect(pathnameFilter?.value).toEqual(expectedPathnameValue)

            const hostFilter = filterFor(filters, '$host')
            expect(hostFilter?.value).toEqual(expectedHostValue)
            expect(hostFilter?.operator).toEqual(PropertyOperator.Exact)
        }
    )
})

describe('cleanPageURLForDisplay', () => {
    const idRule: PathCleaningFilter[] = [{ regex: '\\d+', alias: ':id' }]

    test.each([
        {
            name: 'no rules returns the URL unchanged',
            url: 'https://posthog.com/files/123/',
            filters: [] as PathCleaningFilter[],
            expected: 'https://posthog.com/files/123/',
        },
        {
            name: 'cleans the pathname and keeps the host',
            url: 'https://posthog.com/files/123/',
            filters: idRule,
            expected: 'posthog.com/files/:id/',
        },
        {
            name: 'cleans a host-less URL',
            url: 'posthog.com/files/123',
            filters: idRule,
            expected: 'posthog.com/files/:id',
        },
        {
            name: 'applies rules in order',
            url: 'posthog.com/files/123',
            filters: [
                { regex: '\\d+', alias: ':id' },
                { regex: '/files', alias: '/f' },
            ],
            expected: 'posthog.com/f/:id',
        },
        {
            name: 'skips invalid regex rules',
            url: 'posthog.com/files/123',
            filters: [
                { regex: '[', alias: 'x' },
                { regex: '\\d+', alias: ':id' },
            ],
            expected: 'posthog.com/files/:id',
        },
    ])('$name', ({ url, filters, expected }) => {
        expect(cleanPageURLForDisplay(url, filters)).toEqual(expected)
    })
})

describe('buildPageUrlOptions', () => {
    const idRule: PathCleaningFilter[] = [{ regex: '\\d+', alias: ':id' }]
    const urls = (...list: string[]): { url: string }[] => list.map((url) => ({ url }))

    test('passes raw URLs through when cleaning is disabled', () => {
        expect(buildPageUrlOptions(urls('a.com/p/1', 'a.com/p/2'), null, idRule, false)).toEqual([
            { key: 'a.com/p/1', label: 'a.com/p/1' },
            { key: 'a.com/p/2', label: 'a.com/p/2' },
        ])
    })

    test('passes raw URLs through when there are no cleaning rules', () => {
        expect(buildPageUrlOptions(urls('a.com/p/1'), null, [], true)).toEqual([
            { key: 'a.com/p/1', label: 'a.com/p/1' },
        ])
    })

    test('de-duplicates options by their cleaned form, keeping the first raw URL', () => {
        expect(buildPageUrlOptions(urls('a.com/p/1', 'a.com/p/2', 'a.com/q'), null, idRule, true)).toEqual([
            { key: 'a.com/p/1', label: 'a.com/p/:id' },
            { key: 'a.com/q', label: 'a.com/q' },
        ])
    })

    test('keeps the selected URL as its cleaned group representative', () => {
        expect(buildPageUrlOptions(urls('a.com/p/1', 'a.com/p/2'), 'a.com/p/2', idRule, true)).toEqual([
            { key: 'a.com/p/2', label: 'a.com/p/:id' },
        ])
    })

    test('surfaces the selected URL even when it is absent from the loaded page list', () => {
        expect(buildPageUrlOptions(urls('a.com/p/1'), 'a.com/p/9', idRule, true)).toEqual([
            { key: 'a.com/p/9', label: 'a.com/p/:id' },
        ])
    })
})
