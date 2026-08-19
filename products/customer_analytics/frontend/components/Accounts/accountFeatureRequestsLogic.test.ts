import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import * as generatedApi from '../../generated/api'
import type { FeatureRequestApi } from '../../generated/api.schemas'
import { accountFeatureRequestsLogic } from './accountFeatureRequestsLogic'

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
    account: { id: 'account-1', name: 'Acme' },
    account_links: [
        {
            id: 'link-1',
            account: { id: 'account-1', name: 'Acme' },
            evidence: [],
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
})
