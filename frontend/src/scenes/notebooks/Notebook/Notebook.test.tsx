import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'
import { useLayoutEffect } from 'react'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { notebookSceneLogic } from '../notebookSceneLogic'
import { NotebookType } from '../types'
import { buildMarkdownNotebookContent } from './markdownNotebookV2'
import { Notebook } from './Notebook'
import { notebookLogic } from './notebookLogic'

jest.mock('./migrations/migrate', () => {
    const actual = jest.requireActual('./migrations/migrate')
    return {
        ...actual,
        migrate: jest.fn(async (notebook) => notebook),
    }
})

const SHORT_ID = 'test-notebook-load-states'

const notebook = {
    id: 'notebook-id',
    short_id: SHORT_ID,
    title: 'Test',
    content: buildMarkdownNotebookContent('# Title'),
    text_content: '# Title',
    version: 1,
    deleted: false,
    is_template: false,
    user_access_level: AccessControlLevel.Editor,
    created_at: '2025-01-01T00:00:00Z',
    created_by: null,
    last_modified_at: '2025-01-01T00:00:00Z',
    last_modified_by: null,
} as unknown as NotebookType

describe('Notebook load states', () => {
    let logic: ReturnType<typeof notebookLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.REVAMPED_PY_NOTEBOOKS], {
            [FEATURE_FLAGS.REVAMPED_PY_NOTEBOOKS]: true,
        })
        jest.spyOn(api.notebooks, 'collabStream').mockResolvedValue(undefined as any)
        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook' })
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('requests the notebook on mount, so it never reads as missing first', () => {
        const get = jest.spyOn(api.notebooks, 'get').mockReturnValue(new Promise(() => {}) as any)

        logic.mount()

        expect(get).toHaveBeenCalledWith(SHORT_ID, undefined, expect.anything())
        expect(logic.values.notebookLoading).toBe(true)
        expect(logic.values.notebookMissing).toBe(false)
        logic.unmount()
    })

    it('paints the loading state, not "not found", on the first commit', () => {
        jest.spyOn(api.notebooks, 'get').mockReturnValue(new Promise(() => {}) as any)

        // A layout effect runs on the first commit, before the browser paints and before any
        // mount effect, so it sees exactly what the user would see in that first frame.
        let firstCommit = ''
        function FirstCommitProbe(): null {
            useLayoutEffect(() => {
                firstCommit = document.body.innerHTML
            }, [])
            return null
        }

        render(
            <>
                <Notebook shortId={SHORT_ID} mode="notebook" />
                <FirstCommitProbe />
            </>
        )

        expect(firstCommit).not.toContain('not-found-notebook')
        expect(firstCommit).toContain('LemonSkeleton')
    })

    it('offers a retry when the load fails, instead of "not found"', async () => {
        const get = jest.spyOn(api.notebooks, 'get').mockRejectedValue(new Error('network down'))

        render(<Notebook shortId={SHORT_ID} mode="notebook" />)

        expect(await screen.findByText(/We couldn't load this notebook/)).toBeTruthy()
        expect(screen.queryByTestId('not-found-notebook')).toBeNull()
        await expectLogic(logic).toMatchValues({ notebookMissing: false, notebookLoadFailed: true })

        get.mockResolvedValue(notebook)
        await act(async () => {
            fireEvent.click(screen.getAllByText('Try again')[0])
        })

        await waitFor(() => expect(screen.queryByText(/We couldn't load this notebook/)).toBeNull())
        await expectLogic(logic).toMatchValues({ notebookLoadFailed: false })
    })

    it('shows only the retry banner when the server fails the load, not a second error toast', async () => {
        jest.spyOn(api.notebooks, 'get').mockRejectedValue({ status: 500, detail: 'Something went wrong' })
        const toast = jest.spyOn(lemonToast, 'error').mockImplementation(() => undefined as any)

        render(<Notebook shortId={SHORT_ID} mode="notebook" />)

        expect(await screen.findByText(/We couldn't load this notebook/)).toBeTruthy()
        expect(toast).not.toHaveBeenCalled()
    })

    it('shows the access-denied screen, not a retry that cannot succeed', async () => {
        jest.spyOn(api.notebooks, 'get').mockRejectedValue({ status: 403, code: 'permission_denied' })

        const { container, findByText } = render(<Notebook shortId={SHORT_ID} mode="notebook" />)

        expect(await findByText('Access denied')).toBeTruthy()
        expect(container.textContent).not.toContain("We couldn't load this notebook")
    })

    it('requests the notebook once when the scene mounts it', async () => {
        const get = jest.spyOn(api.notebooks, 'get').mockResolvedValue(notebook)

        const sceneLogic = notebookSceneLogic({ shortId: SHORT_ID })
        sceneLogic.mount()
        await expectLogic(notebookLogic({ shortId: SHORT_ID })).toDispatchActions(['loadNotebookSuccess'])

        expect(get).toHaveBeenCalledTimes(1)
        sceneLogic.unmount()
    })

    it('does not label a failed load as not found in the breadcrumbs', async () => {
        jest.spyOn(api.notebooks, 'get').mockRejectedValue(new Error('network down'))

        const sceneLogic = notebookSceneLogic({ shortId: SHORT_ID })
        sceneLogic.mount()
        await expectLogic(notebookLogic({ shortId: SHORT_ID })).toDispatchActions(['loadNotebookFailure'])

        expect(sceneLogic.values.breadcrumbs.at(-1)?.name).toBeNull()
        sceneLogic.unmount()
    })

    it('counts a failed load once per mount, however many retries fail', async () => {
        jest.spyOn(api.notebooks, 'get').mockRejectedValue({ status: 500 })
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)

        render(<Notebook shortId={SHORT_ID} mode="notebook" />)
        expect(await screen.findByText(/We couldn't load this notebook/)).toBeTruthy()

        await act(async () => {
            fireEvent.click(screen.getAllByText('Try again')[0])
        })
        await expectLogic(logic).toDispatchActions(['loadNotebookFailure', 'loadNotebookFailure'])

        expect(capture.mock.calls.filter(([event]) => event === 'notebook load failed')).toHaveLength(1)
    })

    it('does not count a reload that fails while the notebook is still on screen', async () => {
        const get = jest.spyOn(api.notebooks, 'get').mockResolvedValue(notebook)
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)

        render(<Notebook shortId={SHORT_ID} mode="notebook" />)
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toMatchValues({ notebook })

        get.mockRejectedValue({ status: 500 })
        await act(async () => {
            logic.actions.loadNotebook()
        })
        await expectLogic(logic).toDispatchActions(['loadNotebookFailure'])

        expect(capture.mock.calls.filter(([event]) => event === 'notebook load failed')).toHaveLength(0)
    })

    it('shows "not found" when the notebook does not exist', async () => {
        jest.spyOn(api.notebooks, 'get').mockRejectedValue({ status: 404 })

        render(<Notebook shortId={SHORT_ID} mode="notebook" />)

        expect(await screen.findByTestId('not-found-notebook')).toBeTruthy()
        await expectLogic(logic).toMatchValues({ notebookMissing: true, notebookLoadFailed: false })
    })
})
