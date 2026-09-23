import { expectLogic } from 'kea-test-utils'

import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'

import { codeEditorLogic } from '../codeEditorLogic'

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn(),
}))

const performQueryMock = performQuery as jest.Mock

describe('codeEditorLogic', () => {
    let logic: ReturnType<typeof codeEditorLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = codeEditorLogic({
            key: 'test',
            query: 'SELECT sa',
            language: 'hogQL',
            monaco: {} as any,
            editor: { getModel: () => ({}) } as any,
        })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        performQueryMock.mockReset()
    })

    it('keeps a rejected metadata request out of the failure path', async () => {
        performQueryMock.mockRejectedValue({ status: 400, detail: 'Syntax error' })

        await expectLogic(logic, () => {
            logic.actions.reloadMetadata()
        })
            .delay(400)
            .toDispatchActions(['reloadMetadataSuccess'])
            .toNotHaveDispatchedActions(['reloadMetadataFailure'])
            .toMatchValues({ metadata: null })
    })
})
