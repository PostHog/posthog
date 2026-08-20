import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import * as generatedApi from '../../generated/api'
import type { AccountApi, FeatureRequestApi } from '../../generated/api.schemas'
import {
    FEATURE_REQUESTS_PAGE_SIZE,
    featureRequestSearchParams,
    featureRequestsLogic,
    parseFeatureRequestSearchParams,
} from './featureRequestsLogic'

const account: AccountApi = {
    id: 'account-1',
    name: 'Acme',
    notebooks: [],
    ignored_at: null,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    updated_at: null,
}

const createdRequest: FeatureRequestApi = {
    id: 'request-1',
    title: 'Export account-level retention data',
    description: 'The customer needs this for reporting.',
    request_status: 'requested',
    request_priority: null,
    is_archived: false,
    archived_at: null,
    archived_by: null,
    version: 1,
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
                '/api/projects/:team_id/feature_requests/:id/history/': [],
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

    it('allows a request without a description', async () => {
        const createSpy = jest.spyOn(generatedApi, 'featureRequestsCreate').mockResolvedValue(createdRequest)
        logic.actions.openCreateRequest()
        logic.actions.setTitle(createdRequest.title)
        logic.actions.setAccountId(createdRequest.account.id)
        logic.actions.setProductAreaIds(['area-1'])

        await expectLogic(logic, () => logic.actions.submitRequest()).toFinishAllListeners()

        expect(createSpy).toHaveBeenCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.objectContaining({ description: '' })
        )
    })

    it('keeps the selected account name while search results reload', () => {
        logic.actions.loadAccountsSuccess([account])
        logic.actions.setAccountId(account.id)
        logic.actions.loadAccountsSuccess([])

        expect(logic.values.accountOptions).toEqual([{ key: account.id, label: account.name }])
    })

    it('filters product areas by name without changing the available areas', () => {
        const productArea = createdRequest.product_areas[0]
        const dataPlatformArea = { ...productArea, id: 'area-2', name: 'Data platform' }
        logic.actions.loadProductAreasSuccess([productArea, dataPlatformArea])

        logic.actions.setProductAreaSearch(' DATA ')

        expect(logic.values.filteredProductAreas).toEqual([dataPlatformArea])
        expect(logic.values.productAreas).toEqual([productArea, dataPlatformArea])
    })

    it('keeps the product area form hidden until adding or editing an area', async () => {
        await expectLogic(logic, () => logic.actions.openProductAreas()).toFinishAllListeners()

        expect(logic.values.productAreaFormOpen).toBe(false)

        logic.actions.startNewProductArea()
        expect(logic.values.productAreaFormOpen).toBe(true)
        expect(logic.values.editingProductAreaId).toBeNull()

        logic.actions.closeProductAreaForm()
        logic.actions.startEditingProductArea(createdRequest.product_areas[0])
        expect(logic.values.productAreaFormOpen).toBe(true)
        expect(logic.values.editingProductAreaId).toBe('area-1')
    })

    it('keeps a newer product area draft open when an earlier save finishes', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const productArea = createdRequest.product_areas[0]
        const secondProductArea = { ...productArea, id: 'area-2', name: 'Data platform' }
        let resolveUpdate: (area: typeof productArea) => void = () => undefined
        const updatePromise = new Promise<typeof productArea>((resolve) => {
            resolveUpdate = resolve
        })
        jest.spyOn(generatedApi, 'featureRequestProductAreasPartialUpdate').mockReturnValue(updatePromise)
        logic.actions.startEditingProductArea(productArea)
        logic.actions.setProductAreaName('Updated product analytics')

        logic.actions.saveProductArea()
        logic.actions.startEditingProductArea(secondProductArea)
        resolveUpdate({ ...productArea, name: 'Updated product analytics' })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.productAreaFormOpen).toBe(true)
        expect(logic.values.editingProductAreaId).toBe(secondProductArea.id)
        expect(logic.values.productAreaName).toBe(secondProductArea.name)
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
        expect(logic.values.productAreaFormOpen).toBe(false)
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

        expect(listSpy).toHaveBeenCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.objectContaining({
                limit: FEATURE_REQUESTS_PAGE_SIZE,
                offset: FEATURE_REQUESTS_PAGE_SIZE,
                archive_state: 'active',
                request_ordering: '-updated_at',
            })
        )
        expect(logic.values.featureRequestsPage).toBe(2)
        expect(logic.values.featureRequestsResponse.count).toBe(21)
        expect(logic.values.featureRequestsResponse.results).toEqual([createdRequest])
    })

    it('round-trips list filters through URL search parameters', () => {
        const parsed = parseFeatureRequestSearchParams({
            search: 'retention',
            status: 'planned,completed,invalid',
            priority: 'high,none',
            product_area: 'area-1,area-2',
            account: 'account-1',
            archive: 'all',
            sort: 'title',
            page: '3',
        })

        expect(parsed).toMatchObject({
            searchQuery: 'retention',
            statusFilter: ['planned', 'completed'],
            priorityFilter: ['high', 'none'],
            productAreaFilter: ['area-1', 'area-2'],
            accountFilter: ['account-1'],
            archiveState: 'all',
            requestOrdering: 'title',
            featureRequestsPage: 3,
        })
        expect(featureRequestSearchParams(parsed)).toEqual({
            search: 'retention',
            status: 'planned,completed',
            priority: 'high,none',
            product_area: 'area-1,area-2',
            account: 'account-1',
            archive: 'all',
            sort: 'title',
            page: '3',
        })
    })

    it('keeps an edit draft after a stale write and reloads only its version', async () => {
        jest.spyOn(generatedApi, 'featureRequestsUpdate').mockRejectedValueOnce(new ApiError('Conflict', 409))
        jest.spyOn(generatedApi, 'featureRequestsRetrieve').mockResolvedValue({ ...createdRequest, version: 2 })
        logic.actions.setActiveRequestId(createdRequest.id)
        logic.actions.openEditRequest(createdRequest)
        logic.actions.setEditTitle('Unsaved title')

        await expectLogic(logic, () => logic.actions.saveRequestChanges()).toFinishAllListeners()

        expect(logic.values.editRequestOpen).toBe(true)
        expect(logic.values.editTitle).toBe('Unsaved title')
        expect(logic.values.editExpectedVersion).toBe(1)
        expect(logic.values.editError).toContain('changed since')
        expect(logic.values.editIsStale).toBe(true)

        await expectLogic(logic, () => logic.actions.reloadLatestForEdit()).toFinishAllListeners()

        expect(logic.values.editTitle).toBe('Unsaved title')
        expect(logic.values.editExpectedVersion).toBe(2)
        expect(logic.values.editError).toBeNull()
        expect(logic.values.editIsStale).toBe(false)
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
