import { act, fireEvent, render } from '@testing-library/react'
import { BindLogic } from 'kea'
import { expectLogic } from 'kea-test-utils'
import { useState } from 'react'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { NotebookType } from '../types'
import { buildMarkdownNotebookContent } from './markdownNotebookV2'
import { MarkdownNotebookV2 } from './MarkdownNotebookV2Renderer'
import { Notebook } from './Notebook'
import { NotebookLogicProps, notebookLogic } from './notebookLogic'
import { NotebookExpandButton, NotebookKernelInfoButton } from './NotebookMeta'
import { notebookSettingsLogic } from './notebookSettingsLogic'

jest.mock('./migrations/migrate', () => {
    const actual = jest.requireActual('./migrations/migrate')
    return {
        ...actual,
        migrate: jest.fn(async (notebook) => notebook),
    }
})

const SHORT_ID = 'test-markdown-renderer-ui'
const BASE_MARKDOWN = `# Title

Base paragraph`

const cachedNotebook: NotebookType = {
    id: 'notebook-id',
    short_id: SHORT_ID,
    title: 'Test',
    content: buildMarkdownNotebookContent(BASE_MARKDOWN),
    text_content: BASE_MARKDOWN,
    version: 1,
    deleted: false,
    is_template: false,
    user_access_level: AccessControlLevel.Editor,
    created_at: '2025-01-01T00:00:00Z',
    created_by: null,
    last_modified_at: '2025-01-01T00:00:00Z',
    last_modified_by: null,
} as unknown as NotebookType

describe('MarkdownNotebookV2Renderer UI', () => {
    let logic: ReturnType<typeof notebookLogic.build>
    let settingsLogic: ReturnType<typeof notebookSettingsLogic.build>

    beforeEach(async () => {
        localStorage.clear()
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.NOTEBOOK_PYTHON], {
            [FEATURE_FLAGS.NOTEBOOK_PYTHON]: true,
        })
        jest.spyOn(api.notebooks, 'collabStream').mockResolvedValue(undefined as any)

        const logicProps: NotebookLogicProps = { shortId: SHORT_ID, mode: 'notebook', cachedNotebook }
        logic = notebookLogic(logicProps)
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()
        logic.actions.setEditable(true)

        settingsLogic = notebookSettingsLogic()
        settingsLogic.mount()
        settingsLogic.actions.setShowKernelInfo(false)
    })

    afterEach(() => {
        logic?.unmount()
        settingsLogic?.unmount()
        jest.restoreAllMocks()
    })

    it('opens kernel info from the header control and closes markdown source', () => {
        const logicProps: NotebookLogicProps = { shortId: SHORT_ID, mode: 'notebook', cachedNotebook }
        const onDebugOpenChange = jest.fn()

        function ControlledMarkdownNotebookWithHeader(): JSX.Element {
            const [debugOpen, setDebugOpen] = useState(true)

            return (
                <BindLogic logic={notebookLogic} props={logicProps}>
                    <NotebookKernelInfoButton
                        type="secondary"
                        size="small"
                        onBeforeShowKernelInfo={() => setDebugOpen(false)}
                    >
                        Kernel
                    </NotebookKernelInfoButton>
                    <MarkdownNotebookV2
                        debugOpen={debugOpen}
                        onDebugOpenChange={(isOpen) => {
                            onDebugOpenChange(isOpen)
                            setDebugOpen(isOpen)
                        }}
                    />
                </BindLogic>
            )
        }

        const { container, getByText } = render(<ControlledMarkdownNotebookWithHeader />)

        expect(container.querySelector('.MarkdownNotebook__debug-drawer')).toBeInstanceOf(HTMLElement)

        fireEvent.click(getByText('Kernel'))

        expect(onDebugOpenChange).not.toHaveBeenCalled()
        expect(settingsLogic.values.showKernelInfo).toBe(true)
        expect(container.querySelector('.MarkdownNotebook__debug-drawer')).toBeNull()
    })

    it('renders markdown notebooks at expanded width by default and respects the markdown collapse setting', () => {
        const { container } = render(<Notebook shortId={SHORT_ID} mode="notebook" cachedNotebook={cachedNotebook} />)
        const notebookElement = container.querySelector('.Notebook')

        expect(notebookElement?.classList.contains('Notebook--expanded')).toBe(true)
        expect(notebookElement?.classList.contains('Notebook--compact')).toBe(false)

        act(() => {
            settingsLogic.actions.setIsMarkdownExpanded(false)
        })

        expect(notebookElement?.classList.contains('Notebook--compact')).toBe(true)
        expect(notebookElement?.classList.contains('Notebook--expanded')).toBe(false)
    })

    it('collapses markdown content width without changing the legacy notebook width setting', () => {
        const { container } = render(
            <NotebookExpandButton type="secondary" size="small" inPanel={false} isMarkdownNotebook />
        )
        const button = container.querySelector('button')

        expect(settingsLogic.values.isMarkdownExpanded).toBe(true)
        expect(settingsLogic.values.isExpanded).toBe(false)
        expect(button).toBeInstanceOf(HTMLButtonElement)

        fireEvent.click(button as HTMLButtonElement)

        expect(settingsLogic.values.isMarkdownExpanded).toBe(false)
        expect(settingsLogic.values.isExpanded).toBe(false)
    })
})
