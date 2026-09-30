import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { QuickFilterContext } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { quickFilterValuesLogic } from './quickFilterValuesLogic'

const context = QuickFilterContext.ErrorTrackingIssueFilters

const VALUES_BY_KEY: Record<string, string[]> = {
    $lib: ['web', 'posthog-python'],
    $browser: ['Chrome', 'Firefox'],
}

describe('quickFilterValuesLogic', () => {
    let requests: URLSearchParams[]
    let failRequests: boolean

    beforeEach(() => {
        requests = []
        failRequests = false
        useMocks({
            get: {
                '/api/projects/:team_id/events/values/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    requests.push(params)
                    if (failRequests) {
                        return [500, { detail: 'error' }]
                    }
                    const search = params.get('value') ?? ''
                    const names = (VALUES_BY_KEY[params.get('key') ?? ''] ?? []).filter((name) =>
                        name.toLowerCase().includes(search.toLowerCase())
                    )
                    return [200, { results: names.map((name) => ({ name })), refreshing: false }]
                },
            },
        })
        initKeaTests()
    })

    const valuesOf = (logic: ReturnType<typeof quickFilterValuesLogic.build>): (string | string[] | null)[] =>
        logic.values.discoveredOptions.map((option) => option.value)

    it('loads each filter on mount without waiting for another', async () => {
        const libLogic = quickFilterValuesLogic({ context, propertyName: '$lib' })
        const browserLogic = quickFilterValuesLogic({ context, propertyName: '$browser' })
        libLogic.mount()
        browserLogic.mount()

        await expectLogic(libLogic).toDispatchActions(['setValues'])
        await expectLogic(browserLogic).toDispatchActions(['setValues'])

        expect(valuesOf(libLogic)).toEqual(['web', 'posthog-python'])
        expect(valuesOf(browserLogic)).toEqual(['Chrome', 'Firefox'])
        expect(requests.map((params) => params.getAll('event_name'))).toEqual([['$exception'], ['$exception']])
    })

    it('serves a cleared search from the cache', async () => {
        const logic = quickFilterValuesLogic({ context, propertyName: '$lib' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['setValues'])

        await expectLogic(logic, () => logic.actions.setSearch('py')).toDispatchActions(['loadValues', 'setValues'])
        expect(valuesOf(logic)).toEqual(['posthog-python'])

        logic.actions.setSearch('')
        expect(valuesOf(logic)).toEqual(['web', 'posthog-python'])
        expect(logic.values.discoveredValuesStatus).toEqual('loaded')
        expect(requests.map((params) => params.get('value'))).toEqual([null, 'py'])
    })

    it('shows an error and retries when the dropdown opens again', async () => {
        failRequests = true
        const logic = quickFilterValuesLogic({ context, propertyName: '$lib' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['setValuesFailed'])
        expect(logic.values.discoveredValuesStatus).toEqual('error')

        failRequests = false
        await expectLogic(logic, () => logic.actions.setSearch('')).toDispatchActions(['loadValues', 'setValues'])
        expect(logic.values.discoveredValuesStatus).toEqual('loaded')
        expect(valuesOf(logic)).toEqual(['web', 'posthog-python'])
    })
})
