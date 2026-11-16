import { waitFor } from '@testing-library/dom'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import * as api from 'products/data_catalog/frontend/generated/api'

import { biCatalogPickerLogic } from './biCatalogPickerLogic'

beforeEach(() => initKeaTests())
afterEach(() => jest.restoreAllMocks())

it('does not let a superseded request failure hide the new search results', async () => {
    let rejectOld!: (error: Error) => void
    const result = { results: [], count: 0, next: null }
    const list = jest
        .spyOn(api, 'dataCatalogMetricsList')
        .mockImplementationOnce(
            () =>
                new Promise((_, reject) => {
                    rejectOld = reject
                })
        )
        .mockResolvedValueOnce(result)
    const logic = biCatalogPickerLogic()
    logic.mount()
    try {
        logic.actions.open()
        await waitFor(() => expect(list).toHaveBeenCalledTimes(1))
        logic.actions.setSearch('new search')
        await waitFor(() => expect(logic.values.metrics).toEqual(result))
        await expectLogic(logic, () => rejectOld(new Error('Old request failed'))).toFinishAllListeners()
        expect(logic.values.error).toBe(false)
        expect(logic.values.metrics).toEqual(result)
    } finally {
        logic.unmount()
    }
})

it('searches across pages and resets to the first page for a new search', async () => {
    const requests: URLSearchParams[] = []
    useMocks({
        get: {
            '/api/projects/:team_id/data_catalog/metrics/': ({ request }) => {
                requests.push(new URL(request.url).searchParams)
                return { results: [{ id: 'example', name: 'revenue' }], next: 'next', count: 21 }
            },
        },
    })
    const logic = biCatalogPickerLogic()
    logic.mount()
    await expectLogic(logic, () => logic.actions.open()).toFinishAllListeners()
    await expectLogic(logic, () => logic.actions.setPage(1)).toFinishAllListeners()
    expect(requests.at(-1)?.get('offset')).toBe('20')
    await expectLogic(logic, () => logic.actions.setSearch(' revenue ')).toFinishAllListeners()
    expect(requests.at(-1)?.get('offset')).toBe('0')
    expect(requests.at(-1)?.get('search')).toBe('revenue')
    expect(logic.values.metrics?.results[0].name).toBe('revenue')
    logic.unmount()
})

it('keeps failures distinct from an empty result and allows retry', async () => {
    let failed = true
    useMocks({
        get: {
            '/api/projects/:team_id/data_catalog/metrics/': () =>
                failed ? [500, { detail: 'Unavailable' }] : { results: [], count: 0, next: null },
        },
    })
    const logic = biCatalogPickerLogic()
    logic.mount()
    await expectLogic(logic, () => logic.actions.open()).toFinishAllListeners()
    expect(logic.values.error).toBe(true)
    failed = false
    await expectLogic(logic, () => logic.actions.loadMetrics()).toFinishAllListeners()
    expect(logic.values.error).toBe(false)
    expect(logic.values.metrics?.results).toEqual([])
    logic.unmount()
})
