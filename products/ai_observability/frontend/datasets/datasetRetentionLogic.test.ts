import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { initKeaTests } from '~/test/init'

import type { DatasetRetentionEntryApi, DatasetRetentionReadApi } from '../generated/api.schemas'
import { datasetRetentionLogic } from './datasetRetentionLogic'
import { datasetsApi } from './datasetsApi'

jest.mock('./datasetsApi', () => ({ datasetsApi: { getRetention: jest.fn(), extendRetention: jest.fn() } }))
jest.mock('lib/lemon-ui/LemonToast')

describe('datasetRetentionLogic', () => {
    const entry: DatasetRetentionEntryApi = {
        dataset_id: 'example-dataset',
        dataset_name: 'Example dataset',
        dataset_archived: false,
        revision: 2,
        expires_at: '2024-01-20T12:00:00Z',
    }
    const response: DatasetRetentionReadApi = {
        datasets_count: 0,
        revisions_count: 1,
        count: 0,
        results: [],
    }
    const api = jest.mocked(datasetsApi)

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        api.getRetention.mockImplementation(async (params) => ({
            ...response,
            count: params?.kind === 'revisions' ? 1 : 0,
            results: params?.kind === 'revisions' ? [entry] : [],
        }))
        api.extendRetention.mockResolvedValue({ ...entry, expires_at: '2024-02-15T12:00:00Z' })
    })

    it('finds expiring revisions without opening or renewing the dataset', async () => {
        const logic = datasetRetentionLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.kind).toBe('revisions')
        expect(logic.values.expanded).toBe(false)
        expect(logic.values.warning).toBe('1 older revision expiring within 7 days')
        expect(logic.values.retention?.results).toEqual([entry])
        expect(api.extendRetention).not.toHaveBeenCalled()
        await expectLogic(logic, () => logic.actions.reportOpen(entry)).toFinishAllListeners()
        expect(api.extendRetention).not.toHaveBeenCalled()
    })

    it.each([null, 2])(
        'renews only the requested scope and refreshes warning counts for revision %s',
        async (revision) => {
            const logic = datasetRetentionLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            api.getRetention.mockResolvedValue({ datasets_count: 0, revisions_count: 0, count: 0, results: [] })
            api.extendRetention.mockResolvedValue({ ...entry, revision })
            await expectLogic(logic, () => logic.actions.extendRetention({ ...entry, revision }))
                .toMatchValues({ extendingKey: `example-dataset:${revision ?? 'latest'}` })
                .toFinishAllListeners()
            expect(api.extendRetention).toHaveBeenCalledWith('example-dataset', revision ?? undefined)
            expect(logic.values.extendingKey).toBeNull()
            expect(logic.values.warning).toBe('')
            expect(lemonToast.success).toHaveBeenCalled()
        }
    )

    it('keeps the list actionable after a failed renewal and rechecks entries that may have expired', async () => {
        const logic = datasetRetentionLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        api.extendRetention.mockRejectedValueOnce(new Error('Dataset revision not found'))
        const previousLoads = api.getRetention.mock.calls.length
        await expectLogic(logic, () => logic.actions.extendRetention(entry)).toFinishAllListeners()
        expect(logic.values.extendingKey).toBeNull()
        expect(api.getRetention.mock.calls.length).toBeGreaterThan(previousLoads)
        expect(lemonToast.error).toHaveBeenCalled()
    })

    it('refreshes on return from another tab and moves back when the last page disappears', async () => {
        const logic = datasetRetentionLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        api.getRetention.mockResolvedValue({ ...response, revisions_count: 6, count: 6, results: [entry] })
        await expectLogic(logic, () => logic.actions.setPage(2)).toFinishAllListeners()
        expect(api.getRetention).toHaveBeenLastCalledWith({ kind: 'revisions', limit: 5, offset: 5 })
        api.getRetention.mockResolvedValue({ ...response, revisions_count: 5, count: 5, results: [entry] })
        await expectLogic(logic, () => {
            window.dispatchEvent(new Event('focus'))
        }).toFinishAllListeners()
        expect(logic.values.page).toBe(1)
        expect(api.getRetention).toHaveBeenLastCalledWith({ kind: 'revisions', limit: 5, offset: 0 })
    })
})
