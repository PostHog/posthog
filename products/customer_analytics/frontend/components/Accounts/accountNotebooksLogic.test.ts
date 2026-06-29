import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { notebookPanelLogic } from 'scenes/notebooks/NotebookPanel/notebookPanelLogic'

import { initKeaTests } from '~/test/init'

import { accountsNotebooksCreate, accountsNotebooksList } from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountNotebookApi,
    PaginatedAccountNotebookListApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountNotebooksLogic, NOTES_PER_PAGE } from './accountNotebooksLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    accountsNotebooksList: jest.fn(),
    accountsNotebooksCreate: jest.fn(),
}))

const mockList = accountsNotebooksList as jest.MockedFunction<typeof accountsNotebooksList>
const mockCreate = accountsNotebooksCreate as jest.MockedFunction<typeof accountsNotebooksCreate>

const TEAM = String(MOCK_DEFAULT_TEAM.id)

const buildResponse = (
    results: AccountNotebookApi[] = [],
    count: number = results.length
): PaginatedAccountNotebookListApi => ({ results, count, next: null, previous: null })

describe('accountNotebooksLogic', () => {
    let logic: ReturnType<typeof accountNotebooksLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        mockList.mockResolvedValue(buildResponse())
    })

    afterEach(() => {
        logic?.unmount()
    })

    const mount = async (): Promise<void> => {
        logic = accountNotebooksLogic({ accountId: 'acc-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    it('loads the first page with the default ordering', async () => {
        await mount()

        expect(mockList).toHaveBeenLastCalledWith(TEAM, 'acc-1', {
            limit: NOTES_PER_PAGE,
            offset: 0,
            search: undefined,
            ordering: '-created_at',
        })
    })

    it('search resets to the first page and reloads with the search term', async () => {
        await mount()
        logic.actions.setPage(3)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setSearchTerm('renewal')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.page).toBe(1)
        expect(mockList).toHaveBeenLastCalledWith(TEAM, 'acc-1', {
            limit: NOTES_PER_PAGE,
            offset: 0,
            search: 'renewal',
            ordering: '-created_at',
        })
    })

    it('sorting maps the column and direction onto the ordering param', async () => {
        await mount()

        logic.actions.setSorting({ columnKey: 'created_by', order: 1 })
        await expectLogic(logic).toFinishAllListeners()

        expect(mockList).toHaveBeenLastCalledWith(
            TEAM,
            'acc-1',
            expect.objectContaining({ ordering: 'created_by', offset: 0 })
        )
    })

    it('createNote opens the new note in the side panel and reloads the list', async () => {
        await mount()
        mockCreate.mockResolvedValue({ short_id: 'note-1' } as AccountNotebookApi)
        mockList.mockResolvedValue(buildResponse([{ short_id: 'note-1' } as AccountNotebookApi], 1))

        logic.actions.createNote()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockCreate).toHaveBeenCalledTimes(1)
        expect(notebookPanelLogic.values.selectedNotebook).toBe('note-1')
        expect(logic.values.notebooks).toEqual([{ short_id: 'note-1' }])
    })

    it('createNote resets to the first page so the new note is visible', async () => {
        await mount()
        logic.actions.setPage(2)
        await expectLogic(logic).toFinishAllListeners()
        mockCreate.mockResolvedValue({ short_id: 'note-1' } as AccountNotebookApi)

        logic.actions.createNote()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.page).toBe(1)
        expect(mockList).toHaveBeenLastCalledWith(TEAM, 'acc-1', expect.objectContaining({ offset: 0 }))
    })
})
