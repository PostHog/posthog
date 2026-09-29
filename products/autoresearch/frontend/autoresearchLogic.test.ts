import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { autoresearchLogic } from './autoresearchLogic'
import { autoresearchList } from './generated/api'

jest.mock('./generated/api', () => ({
    autoresearchList: jest.fn(),
    autoresearchDestroy: jest.fn(),
    autoresearchPauseCreate: jest.fn(),
    autoresearchResumeCreate: jest.fn(),
}))

const mockList = autoresearchList as jest.Mock

describe('autoresearchLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    function statusLogicValues(): string {
        return productSetupStatusLogic({ productKey: ProductKey.AUTORESEARCH }).values.status
    }

    it.each([
        [0, 'needs-setup'],
        [2, 'has-data'],
    ])('pushes the setup status for %i pipelines so the empty-state gate routes correctly', async (count, expected) => {
        mockList.mockResolvedValue({ results: Array.from({ length: count }, (_, i) => ({ id: String(i) })) })
        const logic = autoresearchLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(statusLogicValues()).toBe(expected)
    })

    it('fails open to unknown when the list load fails with no earlier answer', async () => {
        mockList.mockRejectedValue(new Error('network down'))
        const logic = autoresearchLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(statusLogicValues()).toBe('unknown')
        expect(logic.values.pipelinesLoadFailed).toBe(true)

        mockList.mockReturnValue(new Promise(() => {}))
        logic.actions.loadPipelines()
        expect(logic.values.pipelinesLoadFailed).toBe(false)
    })

    it('follows every page of the list', async () => {
        mockList
            .mockResolvedValueOnce({ results: [{ id: 'a' }, { id: 'b' }], next: 'page-2' })
            .mockResolvedValueOnce({ results: [{ id: 'c' }], next: null })
        const logic = autoresearchLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.pipelines.map((p) => p.id)).toEqual(['a', 'b', 'c'])
        expect(mockList).toHaveBeenLastCalledWith(expect.any(String), { offset: 2 })
    })

    it('loads once when mounted on the list route', async () => {
        mockList.mockResolvedValue({ results: [] })
        router.actions.push(urls.autoresearch())
        const logic = autoresearchLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(mockList).toHaveBeenCalledTimes(1)
    })
})
