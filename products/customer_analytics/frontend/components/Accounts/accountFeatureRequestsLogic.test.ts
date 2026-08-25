import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api'

import { initKeaTests } from '~/test/init'

import * as generatedApi from '../../generated/api'
import type { FeatureRequestApi, PaginatedFeatureRequestListApi } from '../../generated/api.schemas'
import { ACCOUNT_FEATURE_REQUESTS_PAGE_SIZE, accountFeatureRequestsLogic } from './accountFeatureRequestsLogic'

const existingRequest: FeatureRequestApi = {
    id: 'request-1',
    title: 'Scheduled exports',
    description: 'Send exports on a schedule.',
    request_status: 'requested',
    request_priority: null,
    is_archived: false,
    archived_at: null,
    archived_by: null,
    version: 3,
    can_update: true,
    account: { id: 'account-1', name: 'Acme' },
    account_links: [
        {
            id: 'link-1',
            account: { id: 'account-1', name: 'Acme' },
            evidence: [],
            evidence_count: 0,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
        },
    ],
    product_areas: [],
    created_by: 1,
    updated_by: 1,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
}

const emptyPage = { count: 0, next: null, previous: null, results: [] }

describe('accountFeatureRequestsLogic', () => {
    beforeEach(() => {
        initKeaTests(true, MOCK_DEFAULT_TEAM)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('links an existing request without replacing its current accounts', async () => {
        const listSpy = jest
            .spyOn(generatedApi, 'featureRequestsList')
            .mockResolvedValueOnce(emptyPage)
            .mockResolvedValueOnce({ ...emptyPage, count: 1, results: [existingRequest] })
            .mockResolvedValueOnce({ ...emptyPage, count: 1, results: [existingRequest] })
        const updateSpy = jest.spyOn(generatedApi, 'featureRequestsUpdate').mockResolvedValue(existingRequest)
        const logic = accountFeatureRequestsLogic({ accountId: 'account-2' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => logic.actions.openRequestPicker()).toFinishAllListeners()
        logic.actions.setSelectedRequestId(existingRequest.id)
        await expectLogic(logic, () => logic.actions.linkSelectedRequest()).toFinishAllListeners()

        expect(updateSpy).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), existingRequest.id, {
            expected_version: existingRequest.version,
            account_ids: ['account-1', 'account-2'],
        })
        expect(listSpy).toHaveBeenCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.objectContaining({ account_ids: ['account-2'] })
        )
        expect(logic.values.requestPickerOpen).toBe(false)
        expect(logic.values.linkingRequest).toBe(false)
        logic.unmount()
    })

    it('paginates linked requests and searches from the first page', async () => {
        const requests = Array.from({ length: ACCOUNT_FEATURE_REQUESTS_PAGE_SIZE + 1 }, (_, index) => ({
            ...existingRequest,
            id: `request-${index + 1}`,
            title: `Request ${index + 1}`,
        }))
        const listSpy = jest.spyOn(generatedApi, 'featureRequestsList').mockImplementation(async (_teamId, params) => {
            const offset = params?.offset ?? 0
            const limit = params?.limit ?? ACCOUNT_FEATURE_REQUESTS_PAGE_SIZE
            return {
                count: requests.length,
                next: offset + limit < requests.length ? 'next' : null,
                previous: offset > 0 ? 'previous' : null,
                results: requests.slice(offset, offset + limit),
            }
        })
        const logic = accountFeatureRequestsLogic({ accountId: 'account-2' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.accountRequests.results).toHaveLength(ACCOUNT_FEATURE_REQUESTS_PAGE_SIZE)

        await expectLogic(logic, () => logic.actions.setAccountRequestsPage(2)).toFinishAllListeners()

        expect(logic.values.accountRequests.results).toHaveLength(1)
        expect(listSpy).toHaveBeenCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.objectContaining({
                account_ids: ['account-2'],
                limit: ACCOUNT_FEATURE_REQUESTS_PAGE_SIZE,
                offset: ACCOUNT_FEATURE_REQUESTS_PAGE_SIZE,
            })
        )

        await expectLogic(logic, () => logic.actions.setAccountRequestsSearch('scheduled')).toFinishAllListeners()

        expect(logic.values.accountRequestsPage).toBe(1)
        expect(listSpy).toHaveBeenLastCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.objectContaining({
                account_ids: ['account-2'],
                limit: ACCOUNT_FEATURE_REQUESTS_PAGE_SIZE,
                offset: 0,
                search: 'scheduled',
            })
        )
        logic.unmount()
    })

    it('ignores a stale page response after a newer request finishes', async () => {
        let resolvePageTwo: (response: PaginatedFeatureRequestListApi) => void = () => undefined
        let resolvePageThree: (response: PaginatedFeatureRequestListApi) => void = () => undefined
        const pageTwoResponse = new Promise<PaginatedFeatureRequestListApi>((resolve) => {
            resolvePageTwo = resolve
        })
        const pageThreeResponse = new Promise<PaginatedFeatureRequestListApi>((resolve) => {
            resolvePageThree = resolve
        })
        jest.spyOn(generatedApi, 'featureRequestsList')
            .mockResolvedValueOnce(emptyPage)
            .mockImplementation(async (_teamId, params) => {
                if (params?.offset === ACCOUNT_FEATURE_REQUESTS_PAGE_SIZE) {
                    return pageTwoResponse
                }
                if (params?.offset === ACCOUNT_FEATURE_REQUESTS_PAGE_SIZE * 2) {
                    return pageThreeResponse
                }
                return emptyPage
            })
        const logic = accountFeatureRequestsLogic({ accountId: 'account-2' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setAccountRequestsPage(2)
        logic.actions.setAccountRequestsPage(3)
        const requestCount = ACCOUNT_FEATURE_REQUESTS_PAGE_SIZE * 2 + 1
        resolvePageThree({ ...emptyPage, count: requestCount, results: [{ ...existingRequest, id: 'request-page-3' }] })
        resolvePageTwo({ ...emptyPage, count: requestCount, results: [{ ...existingRequest, id: 'request-page-2' }] })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.accountRequestsPage).toBe(3)
        expect(logic.values.accountRequests.results.map((request) => request.id)).toEqual(['request-page-3'])
        logic.unmount()
    })

    it('searches a bounded page and excludes requests the caller cannot update', async () => {
        const readOnlyRequest = { ...existingRequest, id: 'request-2', can_update: false }
        const listSpy = jest
            .spyOn(generatedApi, 'featureRequestsList')
            .mockResolvedValueOnce(emptyPage)
            .mockResolvedValue({ ...emptyPage, count: 2, results: [existingRequest, readOnlyRequest] })
        const logic = accountFeatureRequestsLogic({ accountId: 'account-2' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openRequestPicker()
        await expectLogic(logic, () => logic.actions.setRequestSearch('scheduled')).toFinishAllListeners()

        expect(logic.values.availableRequests).toEqual([existingRequest])
        expect(listSpy).toHaveBeenLastCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.objectContaining({
                archive_state: 'active',
                limit: 50,
                offset: 0,
                search: 'scheduled',
            })
        )
        logic.unmount()
    })

    it('exposes picker load failures for retry', async () => {
        jest.spyOn(console, 'error').mockImplementation()
        jest.spyOn(generatedApi, 'featureRequestsList')
            .mockResolvedValueOnce(emptyPage)
            .mockRejectedValueOnce(new Error('network failure'))
        const logic = accountFeatureRequestsLogic({ accountId: 'account-2' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => logic.actions.openRequestPicker()).toFinishAllListeners()

        expect(logic.values.availableRequestsError).toBe("Couldn't load available feature requests.")
        logic.unmount()
    })

    it('refreshes picker options after a version conflict', async () => {
        const listSpy = jest
            .spyOn(generatedApi, 'featureRequestsList')
            .mockResolvedValueOnce(emptyPage)
            .mockResolvedValue({ ...emptyPage, count: 1, results: [existingRequest] })
        jest.spyOn(generatedApi, 'featureRequestsUpdate').mockRejectedValueOnce(new ApiError('Conflict', 409))
        const logic = accountFeatureRequestsLogic({ accountId: 'account-2' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.openRequestPicker()).toFinishAllListeners()
        logic.actions.setSelectedRequestId(existingRequest.id)

        await expectLogic(logic, () => logic.actions.linkSelectedRequest()).toFinishAllListeners()

        expect(logic.values.selectedRequestId).toBeNull()
        expect(listSpy).toHaveBeenCalledTimes(3)
        expect(logic.values.requestPickerOpen).toBe(true)
        logic.unmount()
    })
})
