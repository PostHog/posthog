import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { HogQLQueryResponse } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { filtersFromParams, parseUsageData, realTimeUsageLogic } from './realTimeUsageLogic'

const response = (results: unknown[][]): HogQLQueryResponse => ({ results }) as HogQLQueryResponse

describe('real-time usage logic', () => {
    it('reads project filters and breakdowns from the URL', () => {
        expect(filtersFromParams({ project_ids: '2,4', breakdown_by_project: true })).toMatchObject({
            projectIds: [2, 4],
            breakdownByProject: true,
        })
        expect(filtersFromParams({ project_ids: '' }).projectIds).toEqual([])
    })

    it('drops project filters that are not in the organization', () => {
        initKeaTests(true, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_PROJECT, { ...MOCK_DEFAULT_ORGANIZATION, teams: [] })
        const logic = realTimeUsageLogic()
        logic.mount()

        logic.actions.setUsageFilters({
            range: '1d',
            granularity: 'hour',
            projectIds: [999],
            breakdownByProject: false,
        })

        expect(logic.values.selectedProjectIds).toEqual([])
    })

    it('keeps projects separate when the project breakdown is enabled', () => {
        const bucket = Math.floor(Date.now() / 1000 / 3600) * 3600
        const usageData = parseUsageData(
            [
                {
                    project: { id: 1, name: 'First project' },
                    usage: response([[bucket, 'ingestion', 'events', 'events', 2]]),
                },
                {
                    project: { id: 2, name: 'Second project' },
                    usage: response([[bucket, 'ingestion', 'events', 'events', 3]]),
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
