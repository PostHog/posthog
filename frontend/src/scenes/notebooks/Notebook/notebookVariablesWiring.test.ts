import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { NotebookType } from '../types'
import { buildMarkdownNotebookContent } from './markdownNotebookV2'
import { notebookLogic } from './notebookLogic'
import { notebookNodeStalenessLogic } from './notebookNodeStalenessLogic'

jest.mock('./migrations/migrate', () => {
    const actual = jest.requireActual('./migrations/migrate')
    return { ...actual, migrate: jest.fn(async (notebook: unknown) => notebook) }
})

const SHORT_ID = 'vars-wiring'

// `sql_cell` reads {country}; `py_cell` reads sql_cell's frame, so it is downstream.
const MARKDOWN = [
    '<SQLV2 nodeId="sql_cell" returnVariable="sql_df" code="select {country} as c" />',
    '<PythonV2 nodeId="py_cell" returnVariable="py_df" code="out = sql_df.head()" />',
].join('\n\n')

const notebookFixture = {
    id: 'notebook-id',
    short_id: SHORT_ID,
    title: 'Variables wiring',
    content: buildMarkdownNotebookContent(MARKDOWN),
    text_content: '',
    version: 1,
    deleted: false,
    is_template: false,
    user_access_level: AccessControlLevel.Editor,
    created_at: '2025-01-01T00:00:00Z',
    created_by: null,
    last_modified_at: '2025-01-01T00:00:00Z',
    last_modified_by: null,
    variables: [{ name: 'country', type: 'string', value: 'US' }],
} as unknown as NotebookType

describe('notebook variables wiring', () => {
    let logic: ReturnType<typeof notebookLogic.build>
    let stalenessLogic: ReturnType<typeof notebookNodeStalenessLogic.build>
    let updateSpy: jest.SpyInstance

    beforeEach(() => {
        localStorage.clear()
        useMocks({
            get: {
                [`/api/projects/@current/notebooks/${SHORT_ID}/`]: () => [200, notebookFixture],
                [`/api/projects/:project_id/notebooks/${SHORT_ID}/`]: () => [200, notebookFixture],
                [`/api/projects/:project_id/notebooks/${SHORT_ID}/kernel/status/`]: () => [200, { backend: null }],
            },
        })
        initKeaTests()
        jest.spyOn(api.notebooks, 'collabStream').mockResolvedValue(undefined as any)
        // Echoes the saved variables, as the API does. Returning the fixture unchanged would
        // hide a save that never reaches the bar.
        updateSpy = jest
            .spyOn(api.notebooks, 'update')
            .mockImplementation(async (_shortId: string, data: Record<string, any>) => ({
                ...notebookFixture,
                ...data,
            }))

        stalenessLogic = notebookNodeStalenessLogic({ shortId: SHORT_ID })
        stalenessLogic.mount()
        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook', cachedNotebook: notebookFixture })
        logic.mount()
        logic.actions.loadNotebook()
    })

    // The save debounces by 500ms, so the request appears only after it elapses. Polled rather
    // than slept past, so a slow machine waits longer instead of failing.
    const waitForSaveRequests = async (count: number): Promise<void> => {
        for (let attempt = 0; attempt < 200; attempt++) {
            if (updateSpy.mock.calls.length >= count) {
                return
            }
            await new Promise((resolve) => setTimeout(resolve, 20))
        }
        throw new Error(`Expected ${count} save requests, saw ${updateSpy.mock.calls.length}`)
    }

    afterEach(() => {
        logic?.unmount()
        stalenessLogic?.unmount()
        jest.restoreAllMocks()
    })

    it('changing a value through the bar marks the reading cell and its downstream stale', async () => {
        await expectLogic(logic).toFinishAllListeners()
        // Goes through the action the bar actually dispatches. Asserting `variablesChanged`
        // directly would pass even with the listener unwired, which is how this regressed.
        logic.actions.setVariables([{ name: 'country', type: 'string', value: 'DE' }])
        await expectLogic(logic).toFinishAllListeners()

        expect(stalenessLogic.values.staleNodeIds).toEqual({ sql_cell: 'variable', py_cell: 'variable' })
    })

    it('reads the saved variables off the notebook', async () => {
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.variables).toEqual([{ name: 'country', type: 'string', value: 'US' }])
    })

    it('keeps the saved value once the save lands', async () => {
        // The notebook this logic renders from is not the list row notebooksModel holds, so the
        // save has to be written back to it. Without that the bar drops the local copy and falls
        // back to the list the page loaded with, reverting the edit the person just made.
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setVariables([{ name: 'country', type: 'string', value: 'DE' }])
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.variables).toEqual([{ name: 'country', type: 'string', value: 'DE' }])
        expect(logic.values.syncStatus).toEqual('synced')
    })

    it('adding an empty row neither saves nor reports an error', async () => {
        // Clicking "Add variable" used to PATCH a nameless row straight away: the API rejected it
        // and the person got an error toast for a row they had not started filling in.
        await expectLogic(logic).toFinishAllListeners()
        updateSpy.mockClear()

        logic.actions.setVariables([
            { name: 'country', type: 'string', value: 'US' },
            { name: '', type: 'string', value: '' },
        ])
        await expectLogic(logic).toFinishAllListeners()

        expect(updateSpy).not.toHaveBeenCalled()
        expect(logic.values.variableErrors).toEqual([null, null])
        expect(logic.values.syncStatus).toEqual('synced')
    })

    it('an unnamed row does not hold back an edit to a named one', async () => {
        // The draft is withheld from the PATCH rather than blocking it, and it stays in the bar
        // so the person can carry on naming it.
        await expectLogic(logic).toFinishAllListeners()
        updateSpy.mockClear()

        logic.actions.setVariables([
            { name: 'country', type: 'string', value: 'DE' },
            { name: '', type: 'string', value: '' },
        ])
        await expectLogic(logic).toFinishAllListeners()

        expect(updateSpy).toHaveBeenCalledWith(SHORT_ID, {
            variables: [{ name: 'country', type: 'string', value: 'DE' }],
        })
        expect(logic.values.variables).toEqual([
            { name: 'country', type: 'string', value: 'DE' },
            { name: '', type: 'string', value: '' },
        ])
    })

    it.each([
        ['an invalid name', '2days'],
        ['a cleared name', ''],
    ])('holds the save while a saved variable carries %s', async (_case, name) => {
        // The payload replaces the whole list, so sending it without the unsendable row would
        // delete `country` on the server. A typo must not drop the value the row holds.
        await expectLogic(logic).toFinishAllListeners()
        updateSpy.mockClear()

        logic.actions.setVariables([{ name, type: 'string', value: 'US' }])
        await expectLogic(logic).toFinishAllListeners()

        expect(updateSpy).not.toHaveBeenCalled()
        // Nothing reached the server, so the bar has to keep saying so.
        expect(logic.values.syncStatus).toEqual('unsaved')
    })

    it('removing a variable still saves the removal', async () => {
        // The guard above must not block a deletion: a removed row leaves nothing on screen.
        await expectLogic(logic).toFinishAllListeners()
        updateSpy.mockClear()

        logic.actions.setVariables([])
        await expectLogic(logic).toFinishAllListeners()

        expect(updateSpy).toHaveBeenCalledWith(SHORT_ID, { variables: [] })
        expect(logic.values.variables).toEqual([])
    })

    it('ignores a save response that lands after a newer one', async () => {
        // The debounce holds the next request but does not cancel one in flight, so two saves can
        // overlap. The slower, older response must not revert the bar to the list it replaced.
        await expectLogic(logic).toFinishAllListeners()
        updateSpy.mockClear()

        const pending: Array<() => void> = []
        updateSpy.mockImplementation(
            (_shortId: string, data: Record<string, any>) =>
                new Promise((resolve) => pending.push(() => resolve({ ...notebookFixture, ...data })))
        )

        logic.actions.setVariables([{ name: 'country', type: 'string', value: 'FIRST' }])
        await waitForSaveRequests(1)
        logic.actions.setVariables([{ name: 'country', type: 'string', value: 'SECOND' }])
        await waitForSaveRequests(2)

        // Newer first, then the straggler.
        pending[1]()
        pending[0]()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.variables).toEqual([{ name: 'country', type: 'string', value: 'SECOND' }])
    })

    it('an edit counts as unsaved work until the save lands', async () => {
        // Variables save on their own PATCH, so the document being clean must not report
        // "synced" while a variable edit is still pending — that also drives the
        // navigate-away warning.
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setVariables([{ name: 'country', type: 'string', value: 'DE' }])
        expect(logic.values.syncStatus).toEqual('unsaved')

        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.localVariables).toBeNull()
    })
})
