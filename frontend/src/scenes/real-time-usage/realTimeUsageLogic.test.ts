import { HogQLQueryResponse } from '~/queries/schema/schema-general'

import { filtersFromParams, parseUsageData } from './realTimeUsageLogic'

const response = (results: unknown[][]): HogQLQueryResponse => ({ results }) as HogQLQueryResponse

describe('real-time usage logic', () => {
    it('reads project filters and breakdowns from the URL', () => {
        expect(filtersFromParams({ project_ids: '2,4', breakdown_by_project: 'true' })).toMatchObject({
            projectIds: [2, 4],
            breakdownByProject: true,
        })
        expect(filtersFromParams({ project_ids: '' }).projectIds).toEqual([])
    })

    it('keeps projects separate when the project breakdown is enabled', () => {
        const bucket = Math.floor(Date.now() / 1000 / 3600) * 3600
        const usageData = parseUsageData(
            [
                {
                    project: { id: 1, name: 'First project' },
                    rows: response([['ingestion', 'events', 'events', 2]]),
                    timeSeries: response([[bucket, 'ingestion: events (events)', 2]]),
                },
                {
                    project: { id: 2, name: 'Second project' },
                    rows: response([['ingestion', 'events', 'events', 3]]),
                    timeSeries: response([[bucket, 'ingestion: events (events)', 3]]),
                },
            ],
            '1d',
            'hour',
            true
        )

        expect(usageData.rows).toEqual([
            { projectName: 'Second project', producerId: 'ingestion', usageKey: 'events', unit: 'events', quantity: 3 },
            { projectName: 'First project', producerId: 'ingestion', usageKey: 'events', unit: 'events', quantity: 2 },
        ])
        expect(usageData.timeSeries.series.map((series) => series.name)).toEqual([
            'First project: ingestion: events (events)',
            'Second project: ingestion: events (events)',
        ])
    })
})
