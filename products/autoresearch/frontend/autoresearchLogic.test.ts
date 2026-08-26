import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

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
    })
})
