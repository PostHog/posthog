import {
    addAssetError,
    emptyGroupedAssetErrors,
    formatGroupedAssetErrors,
    ResourceErrorDetails,
} from './utils/asset-error-grouping'

function groupAll(errors: ResourceErrorDetails[]): ReturnType<typeof formatGroupedAssetErrors> {
    const group = emptyGroupedAssetErrors()
    for (const err of errors) {
        addAssetError(group, err)
    }
    return formatGroupedAssetErrors(group)
}

describe('asset error grouping', () => {
    it.each([
        {
            name: 'groups CSP violations by directive',
            errors: [
                { resourceType: 'csp', resourceUrl: 'img1.png', message: 'CSP violation: img-src', error: null },
                { resourceType: 'csp', resourceUrl: 'img2.png', message: 'CSP violation: img-src', error: null },
                { resourceType: 'csp', resourceUrl: 'font.woff', message: 'CSP violation: font-src', error: null },
            ] as ResourceErrorDetails[],
            expected: {
                'CSP violations (3)': { 'img-src': 2, 'font-src': 1 },
            },
        },
        {
            name: 'groups non-CSP errors by type with unique URLs',
            errors: [
                {
                    resourceType: 'stylesheet',
                    resourceUrl: 'a.css',
                    message: 'Failed to load stylesheet',
                    error: undefined,
                },
                {
                    resourceType: 'stylesheet',
                    resourceUrl: 'b.css',
                    message: 'Failed to load stylesheet',
                    error: undefined,
                },
                { resourceType: 'img', resourceUrl: 'pic.png', message: 'Failed to load image', error: undefined },
            ] as ResourceErrorDetails[],
            expected: {
                'stylesheet errors (2)': 'a.css, b.css',
                'img errors (1)': 'pic.png',
            },
        },
        {
            name: 'truncates URLs when more than 3 unique',
            errors: [
                { resourceType: 'img', resourceUrl: 'a.png', message: 'Failed', error: undefined },
                { resourceType: 'img', resourceUrl: 'b.png', message: 'Failed', error: undefined },
                { resourceType: 'img', resourceUrl: 'c.png', message: 'Failed', error: undefined },
                { resourceType: 'img', resourceUrl: 'd.png', message: 'Failed', error: undefined },
                { resourceType: 'img', resourceUrl: 'e.png', message: 'Failed', error: undefined },
            ] as ResourceErrorDetails[],
            expected: {
                'img errors (5)': 'a.png, b.png, c.png + 2 more',
            },
        },
        {
            name: 'deduplicates URLs in non-CSP groups',
            errors: [
                { resourceType: 'stylesheet', resourceUrl: 'a.css', message: 'Failed', error: undefined },
                { resourceType: 'stylesheet', resourceUrl: 'a.css', message: 'Failed', error: undefined },
                { resourceType: 'stylesheet', resourceUrl: 'a.css', message: 'Failed', error: undefined },
            ] as ResourceErrorDetails[],
            expected: {
                'stylesheet errors (3)': 'a.css',
            },
        },
        {
            name: 'handles mixed CSP and non-CSP errors',
            errors: [
                { resourceType: 'csp', resourceUrl: 'img.png', message: 'CSP violation: img-src', error: null },
                {
                    resourceType: 'stylesheet',
                    resourceUrl: 'style.css',
                    message: 'Failed to load stylesheet',
                    error: undefined,
                },
            ] as ResourceErrorDetails[],
            expected: {
                'CSP violations (1)': { 'img-src': 1 },
                'stylesheet errors (1)': 'style.css',
            },
        },
        {
            name: 'handles empty array',
            errors: [],
            expected: {},
        },
    ])('$name', ({ errors, expected }) => {
        expect(groupAll(errors)).toEqual(expected)
    })

    it('groups incrementally with the same result as batch', () => {
        const errors: ResourceErrorDetails[] = [
            { resourceType: 'csp', resourceUrl: 'a.png', message: 'CSP violation: img-src', error: null },
            { resourceType: 'csp', resourceUrl: 'b.png', message: 'CSP violation: font-src', error: null },
            { resourceType: 'img', resourceUrl: 'pic.png', message: 'Failed', error: undefined },
        ]

        const group = emptyGroupedAssetErrors()
        for (const err of errors) {
            addAssetError(group, err)
        }

        expect(group.total).toBe(3)
        expect(group.byType['csp'].count).toBe(2)
        expect(group.byType['csp'].cspDirectives).toEqual({ 'img-src': 1, 'font-src': 1 })
        expect(group.byType['img'].count).toBe(1)
        expect(group.byType['img'].urls).toEqual(new Set(['pic.png']))
    })
})
