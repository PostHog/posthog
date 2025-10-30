import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { isSessionSummaryTitle, stripSessionSummaryPrefix } from './NotebookSelectButton'
import { notebookSelectButtonLogic } from './notebookSelectButtonLogic'

describe('NotebookSelectButton helpers', () => {
    test('isSessionSummaryTitle works with various inputs', () => {
        expect(isSessionSummaryTitle(undefined)).toBe(false)
        expect(isSessionSummaryTitle('')).toBe(false)
        expect(isSessionSummaryTitle('Session summaries report - Foo')).toBe(true)
        expect(isSessionSummaryTitle('session summaries report – Bar')).toBe(true)
        expect(isSessionSummaryTitle('Other title')).toBe(false)
    })

    test('stripSessionSummaryPrefix handles edge cases', () => {
        expect(stripSessionSummaryPrefix(undefined as any)).toBeNull()
        expect(stripSessionSummaryPrefix('')).toEqual('')
        expect(stripSessionSummaryPrefix('Session summaries report - Title')).toEqual('Title')
        expect(stripSessionSummaryPrefix('Session summaries report – Title')).toEqual('Title')
        expect(stripSessionSummaryPrefix('Session summaries report: Title')).toEqual('Title')
        expect(stripSessionSummaryPrefix('Session summaries report (2025-10-28)')).toEqual(
            'Session summaries report (2025-10-28)'
        )
        expect(stripSessionSummaryPrefix('Session summaries report - Title (2025-10-28)')).toEqual('Title')
        expect(stripSessionSummaryPrefix('Session summaries report')).toEqual('Session summaries report')
        expect(stripSessionSummaryPrefix('Not a session summary - Title')).toEqual('Not a session summary - Title')
    })
})

describe('notebookSelectButtonLogic filters', () => {
    const emptyResponse = { results: [], count: 0 } as any
    let logic: ReturnType<typeof notebookSelectButtonLogic.build>
    let listMock: jest.SpiedFunction<typeof api.notebooks.list>

    beforeEach(() => {
        initKeaTests()
        listMock = jest.spyOn(api.notebooks, 'list').mockResolvedValue(emptyResponse)
        logic = notebookSelectButtonLogic({})
        logic.mount()
    })

    afterEach(() => {
        jest.restoreAllMocks()
        logic.unmount()
    })

    test('passes search and created_by to api', async () => {
        logic.actions.setSearchQuery('problem')
        logic.actions.setCreatedBy('USER-UUID-1234')

        await expectLogic(logic).delay(350).toFinishAllListeners()

        // There will be two calls (one per listener), assert last call has both params
        const lastCallArgs = listMock.mock.calls.at(-1)?.[0] as Record<string, any>
        expect(lastCallArgs).toEqual(expect.objectContaining({ search: 'problem', created_by: 'USER-UUID-1234' }))
    })
})
