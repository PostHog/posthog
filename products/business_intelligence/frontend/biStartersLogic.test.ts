import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { biStartersLogic } from './biStartersLogic'

it('requests one bounded, server-filtered page per starter list and excludes drifted definitions', async () => {
    initKeaTests()
    let metricParams: Record<string, string> = {}
    let certificationParams: Record<string, string> = {}
    const metrics = jest.fn(({ request }: { request: Request }) => {
        metricParams = Object.fromEntries(new URL(request.url).searchParams)
        return {
            results: [
                { name: 'current', status: 'approved', is_drifted: false, definition_kind: 'HogQLQuery' },
                { name: 'drifted', status: 'approved', is_drifted: true, definition_kind: 'HogQLQuery' },
            ],
            next: 'next-page',
        }
    })
    const certifications = jest.fn(({ request }: { request: Request }) => {
        certificationParams = Object.fromEntries(new URL(request.url).searchParams)
        return { results: [], next: 'next-page' }
    })
    useMocks({
        get: {
            '/api/projects/:team_id/data_catalog/metrics/': metrics,
            '/api/projects/:team_id/data_catalog/certifications/': certifications,
        },
    })
    const logic = biStartersLogic()
    const unmount = logic.mount()
    try {
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.metrics.map((metric) => metric.name)).toEqual(['current'])
        expect(metrics).toHaveBeenCalledTimes(1)
        expect(certifications).toHaveBeenCalledTimes(1)
        expect(metricParams).toEqual({ status: 'approved', definition_kind: 'HogQLQuery', limit: '3' })
        expect(certificationParams).toEqual({ status: 'certified', limit: '3' })
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
