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

const { setLatestVersionsOnQuery } = require('./utils')

// in a separate file to make it easier to mock the LATEST_VERSIONS
describe('setLatestVersionsOnQuery', () => {
    it('adds the latest version', () => {
        const query = {
            kind: 'InsightVizNode',
            source: {
                kind: 'FunnelsQuery',
                series: [
                    {
                        kind: 'EventsNode',
                        event: '$pageview',
                        name: '$pageview',
                    },
                    {
                        kind: 'EventsNode',
                        event: '$pageview',
                        name: 'Pageview',
                    },
                ],
                funnelsFilter: {
                    funnelVizType: 'steps',
                },
            },
            full: true,
        }

        expect(setLatestVersionsOnQuery(query)).toEqual({
            full: true,
            kind: 'InsightVizNode',
            source: {
                funnelsFilter: { funnelVizType: 'steps' },
                kind: 'FunnelsQuery',
                series: [
                    { event: '$pageview', kind: 'EventsNode', name: '$pageview', version: 5 },
                    { event: '$pageview', kind: 'EventsNode', name: 'Pageview', version: 5 },
                ],
                version: 3,
            },
            version: 7,
        })
    })

    it('allows disabling recursing for user provided queries', () => {
        const query = {
            kind: 'InsightVizNode',
            source: {
                kind: 'FunnelsQuery',
                series: [
                    {
                        kind: 'EventsNode',
                        event: '$pageview',
                        name: '$pageview',
                    },
                    {
                        kind: 'EventsNode',
                        event: '$pageview',
                        name: 'Pageview',
                    },
                ],
                funnelsFilter: {
                    funnelVizType: 'steps',
                },
            },
            full: true,
        }

        expect(setLatestVersionsOnQuery(query, { recursion: false })).toEqual({
            full: true,
            kind: 'InsightVizNode',
            source: {
                funnelsFilter: { funnelVizType: 'steps' },
                kind: 'FunnelsQuery',
                series: [
                    { event: '$pageview', kind: 'EventsNode', name: '$pageview' },
                    { event: '$pageview', kind: 'EventsNode', name: 'Pageview' },
                ],
            },
            version: 7,
        })
    })

    it('does not set version for nodes with a kind that is not a NodeKind', () => {
        const query = {
            key: 'some string',
            kind: 'currency',
        }

        expect(setLatestVersionsOnQuery(query)).toEqual({
            key: 'some string',
            kind: 'currency',
        })
    })
})

export {}
