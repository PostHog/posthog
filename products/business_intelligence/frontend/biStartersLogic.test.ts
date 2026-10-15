import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { biStartersLogic } from './biStartersLogic'

it('finds approved starters beyond the first page and excludes drifted definitions', async () => {
    initKeaTests()
    const metrics = jest.fn(({ request }: { request: Request }) => {
        const offset = new URL(request.url).searchParams.get('offset')
        return offset === '0'
            ? { results: [{ name: 'draft', status: 'proposed' }], next: 'next-page' }
            : {
                  results: [
                      { name: 'current', status: 'approved', is_drifted: false, definition_kind: 'HogQLQuery' },
                      { name: 'drifted', status: 'approved', is_drifted: true, definition_kind: 'HogQLQuery' },
                  ],
                  next: null,
              }
    })
    useMocks({
        get: {
            '/api/projects/:team_id/data_catalog/metrics/': metrics,
            '/api/projects/:team_id/data_catalog/certifications/': { results: [], next: null },
        },
    })
    const logic = biStartersLogic()
    const unmount = logic.mount()
    try {
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.metrics.map((metric) => metric.name)).toEqual(['current'])
        expect(metrics).toHaveBeenCalledTimes(2)
    } finally {
        unmount()
    }
})

it('keeps the library usable when optional catalog endpoints are unavailable', async () => {
    initKeaTests()
    useMocks({
        get: {
            '/api/projects/:team_id/data_catalog/metrics/': [403, { detail: 'Unavailable' }],
            '/api/projects/:team_id/data_catalog/certifications/': [403, { detail: 'Unavailable' }],
        },
    })
    const logic = biStartersLogic()
    const unmount = logic.mount()
    try {
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.metrics).toEqual([])
        expect(logic.values.sources).toEqual([])
        expect(logic.values.metricsLoading).toBe(false)
        expect(logic.values.sourcesLoading).toBe(false)
    } finally {
        unmount()
    }
})
