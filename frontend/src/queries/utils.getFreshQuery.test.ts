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
const { getFreshQuery } = require('./utils')

// in a separate file to make it easier to mock the LATEST_VERSIONS
describe('getFreshQuery', () => {
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

        expect(getFreshQuery(query)).toEqual({
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
})

export {}
