jest.mock('./latest-versions', () => {
    return {
        LATEST_VERSIONS: {
            FunnelsQuery: 3,
            EventsNode: 5,
            InsightVizNode: 7,
        },
    }
})

jest.resetModules()

// eslint-disable-next-line @typescript-eslint/no-var-requires
const { checkLatestVersionsOnQuery } = require('./utils')

describe('checkLatestVersionsOnQuery', () => {
    it('returns true if all nodes have the latest version', () => {
        const query = {
            kind: 'InsightVizNode',
            version: 7,
            source: {
                kind: 'FunnelsQuery',
                version: 3,
                series: [
                    { kind: 'EventsNode', event: '$pageview', name: '$pageview', version: 5 },
                    { kind: 'EventsNode', event: '$pageview', name: 'Pageview', version: 5 },
                ],
                funnelsFilter: { funnelVizType: 'steps' },
            },
            full: true,
        }
        expect(checkLatestVersionsOnQuery(query)).toBe(true)
    })

    it('returns false if any node does not have the latest version', () => {
        const query = {
            kind: 'InsightVizNode',
            version: 7,
            source: {
                kind: 'FunnelsQuery',
                version: 2, // not latest
                series: [
                    { kind: 'EventsNode', event: '$pageview', name: '$pageview', version: 5 },
                    { kind: 'EventsNode', event: '$pageview', name: 'Pageview', version: 5 },
                ],
                funnelsFilter: { funnelVizType: 'steps' },
            },
            full: true,
        }
        expect(checkLatestVersionsOnQuery(query)).toBe(false)
    })

    it('returns true for nodes with a kind that is not a NodeKind', () => {
        const query = {
            key: 'some string',
            kind: 'currency',
        }
        expect(checkLatestVersionsOnQuery(query)).toBe(true)
    })

    it('returns true for arrays of nodes with correct versions', () => {
        const arr = [
            { kind: 'EventsNode', event: 'a', version: 5 },
            { kind: 'EventsNode', event: 'b', version: 5 },
        ]
        expect(checkLatestVersionsOnQuery(arr)).toBe(true)
    })

    it('returns false for arrays if any node is not at the latest version', () => {
        const arr = [
            { kind: 'EventsNode', event: 'a', version: 5 },
            { kind: 'EventsNode', event: 'b', version: 4 }, // not latest
        ]
        expect(checkLatestVersionsOnQuery(arr)).toBe(false)
    })
})

export {}
