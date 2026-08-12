import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import * as generatedApi from '../../generated/api'
import type { FeatureRequestApi } from '../../generated/api.schemas'
import { FEATURE_REQUESTS_PAGE_SIZE, featureRequestsLogic } from './featureRequestsLogic'

const createdRequest: FeatureRequestApi = {
    id: 'request-1',
    title: 'Export account-level retention data',
    description: 'The customer needs this for reporting.',
    request_status: 'requested',
    account: { id: 'account-1', name: 'Acme' },
    product_areas: [
        {
            id: 'area-1',
            name: 'Product analytics',
            display_order: 1,
            is_active: true,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
        },
    ],
    created_by: 1,
    updated_by: 1,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
}

describe('featureRequestsLogic', () => {
    let logic: ReturnType<typeof featureRequestsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/feature_requests/': { count: 0, next: null, previous: null, results: [] },
                '/api/projects/:team_id/feature_requests/:id/': createdRequest,
                '/api/projects/:team_id/feature_request_product_areas/': [],
                '/api/projects/:team_id/accounts/': { count: 0, next: null, previous: null, results: [] },
            },
        })
        initKeaTests(true, MOCK_DEFAULT_TEAM)
        logic = featureRequestsLogic()
        logic.mount()
    })

    afterEach(() => {
        jest.restoreAllMocks()
        logic.unmount()
    })

    it('keeps the request fields after a failed save so the editor can retry', async () => {
        jest.spyOn(generatedApi, 'featureRequestsCreate').mockRejectedValueOnce(new Error('save failed'))
        logic.actions.openCreateRequest()
        logic.actions.setTitle(createdRequest.title)
        logic.actions.setDescription(createdRequest.description)
        logic.actions.setAccountId(createdRequest.account.id)
        logic.actions.setProductAreaIds(['area-1'])

        await expectLogic(logic, () => logic.actions.submitRequest()).toFinishAllListeners()

        expect(logic.values.title).toBe(createdRequest.title)
        expect(logic.values.description).toBe(createdRequest.description)
        expect(logic.values.accountId).toBe(createdRequest.account.id)
        expect(logic.values.productAreaIds).toEqual(['area-1'])
        expect(logic.values.createRequestOpen).toBe(true)
        expect(logic.values.submittingRequest).toBe(false)
    })

    it('reloads request rows after a linked product area changes', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const productArea = createdRequest.product_areas[0]
        const renamedRequest: FeatureRequestApi = {
            ...createdRequest,
            product_areas: [{ ...productArea, name: 'Data platform' }],
        }
        jest.spyOn(generatedApi, 'featureRequestProductAreasPartialUpdate').mockResolvedValue({
            ...productArea,
            name: 'Data platform',
        })
        jest.spyOn(generatedApi, 'featureRequestsList').mockResolvedValue({
            count: 1,
            next: null,
            previous: null,
            results: [renamedRequest],
        })
        logic.actions.startEditingProductArea(productArea)
        logic.actions.setProductAreaName('Data platform')

        await expectLogic(logic, () => logic.actions.saveProductArea())
            .toDispatchActions(['loadFeatureRequests', 'loadFeatureRequestsSuccess'])
            .toFinishAllListeners()

        expect(logic.values.featureRequestsResponse.results).toEqual([renamedRequest])
    })

    it('loads the requested page with 20 requests per page', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const listSpy = jest.spyOn(generatedApi, 'featureRequestsList').mockResolvedValue({
            count: 21,
            next: null,
            previous: null,
            results: [createdRequest],
        })

        await expectLogic(logic, () => logic.actions.setFeatureRequestsPage(2))
            .toDispatchActions(['loadFeatureRequests', 'loadFeatureRequestsSuccess'])
            .toFinishAllListeners()

        expect(listSpy).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            limit: FEATURE_REQUESTS_PAGE_SIZE,
            offset: FEATURE_REQUESTS_PAGE_SIZE,
        })
        expect(logic.values.featureRequestsPage).toBe(2)
        expect(logic.values.featureRequestsResponse.count).toBe(21)
        expect(logic.values.featureRequestsResponse.results).toEqual([createdRequest])
    })

    it('ignores a second submit while the first request is in flight', async () => {
        let resolveCreate: (request: FeatureRequestApi) => void = () => undefined
        const createPromise = new Promise<FeatureRequestApi>((resolve) => {
            resolveCreate = resolve
        })
        const createSpy = jest.spyOn(generatedApi, 'featureRequestsCreate').mockReturnValue(createPromise)
        logic.actions.openCreateRequest()
        logic.actions.setTitle(createdRequest.title)
        logic.actions.setDescription(createdRequest.description)
        logic.actions.setAccountId(createdRequest.account.id)
        logic.actions.setProductAreaIds(['area-1'])

        logic.actions.submitRequest()
        logic.actions.submitRequest()
        resolveCreate(createdRequest)
        await expectLogic(logic).toFinishAllListeners()

        expect(createSpy).toHaveBeenCalledTimes(1)
        expect(logic.values.submittingRequest).toBe(false)
    })
})
