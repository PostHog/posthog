import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { tagsModel } from '~/models/tagsModel'
import { initKeaTests } from '~/test/init'

import * as generated from '../generated/api'
import type { TaggedResource } from './resourceTagFilters'
import { resourceTagsLogic } from './resourceTagsLogic'

jest.mock('../generated/api', () => ({
    datasetsPartialUpdate: jest.fn(),
    llmAnalyticsScoreDefinitionsPartialUpdate: jest.fn(),
    aiObservabilityOfflineExperimentsPartialUpdate: jest.fn(),
}))
jest.mock('lib/lemon-ui/LemonToast')

const updates = {
    datasets: jest.mocked(generated.datasetsPartialUpdate),
    scorers: jest.mocked(generated.llmAnalyticsScoreDefinitionsPartialUpdate),
    experiments: jest.mocked(generated.aiObservabilityOfflineExperimentsPartialUpdate),
}

describe('resourceTagsLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        jest.spyOn(api.tags, 'list').mockResolvedValue([])
        tagsModel.mount()
    })

    it.each<TaggedResource>(['datasets', 'scorers', 'experiments'])(
        'saves %s tags only once while a request is pending',
        async (entity) => {
            let finish: () => void = () => {}
            const pending = new Promise<never>((resolve) => {
                finish = () => resolve(undefined as never)
            })
            updates[entity].mockReturnValue(pending)
            const onSaved = jest.fn()
            const logic = resourceTagsLogic({
                entity,
                resourceId: 'resource-id',
                teamId: 997,
                tags: ['before'],
                onSaved,
            })
            logic.mount()
            logic.actions.open()
            logic.actions.setDraft(['quality', 'production'])
            logic.actions.save()
            logic.actions.save()
            expect(logic.values.saving).toBe(true)
            expect(updates[entity]).toHaveBeenCalledTimes(1)
            expect(updates[entity]).toHaveBeenCalledWith('997', 'resource-id', { tags: ['quality', 'production'] })
            await expectLogic(logic, finish).toFinishAllListeners()
            expect(logic.values.saving).toBe(false)
            expect(logic.values.isOpen).toBe(false)
            expect(onSaved).toHaveBeenCalledTimes(1)
        }
    )

    it('keeps the draft after a failed save so it can be retried', async () => {
        updates.datasets.mockRejectedValueOnce(new Error('Failed')).mockResolvedValueOnce({} as never)
        const onSaved = jest.fn()
        const logic = resourceTagsLogic({
            entity: 'datasets',
            resourceId: 'resource-id',
            teamId: 997,
            tags: ['before'],
            onSaved,
        })
        logic.mount()
        logic.actions.open()
        logic.actions.setDraft([])
        await expectLogic(logic, () => logic.actions.save()).toFinishAllListeners()
        expect(logic.values).toMatchObject({ isOpen: true, saving: false, draft: [] })
        expect(logic.values.error).toBeTruthy()
        expect(onSaved).not.toHaveBeenCalled()
        await expectLogic(logic, () => logic.actions.save()).toFinishAllListeners()
        expect(logic.values.error).toBeNull()
        expect(onSaved).toHaveBeenCalledTimes(1)
    })
})
