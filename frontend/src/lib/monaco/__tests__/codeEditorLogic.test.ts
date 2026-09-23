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

    it.each([
        ['a rejected query keeps out of the failure path', 400, 'reloadMetadataSuccess', 'reloadMetadataFailure'],
        ['a server fault still reaches the failure path', 500, 'reloadMetadataFailure', 'reloadMetadataSuccess'],
    ])('%s', async (_name, status, expected, unexpected) => {
        performQueryMock.mockRejectedValue({ status, detail: 'Something went wrong' })

        await expectLogic(logic, () => {
            logic.actions.reloadMetadata()
        })
            .delay(400)
            .toDispatchActions([expected])
            .toNotHaveDispatchedActions([unexpected])
    })
})
