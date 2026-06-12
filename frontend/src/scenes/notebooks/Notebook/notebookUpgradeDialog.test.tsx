import { render } from '@testing-library/react'
import { createElement, Fragment } from 'react'

import { JSONContent } from 'lib/components/RichContentEditor/types'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { NotebookNodeType } from '../types'
import { getMarkdownNotebookMarkdown, isMarkdownNotebookContent } from './markdownNotebookV2'
import { openUpgradeToMarkdownNotebookDialog } from './notebookUpgradeDialog'

jest.mock('lib/lemon-ui/LemonDialog', () => ({
    LemonDialog: {
        open: jest.fn(),
    },
}))

const openDialogMock = LemonDialog.open as jest.Mock

describe('notebookUpgradeDialog', () => {
    beforeEach(() => {
        openDialogMock.mockClear()
    })

    it('warns before converting a notebook to markdown content', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: 'heading',
                    attrs: { level: 1 },
                    content: [{ type: 'text', text: 'Activation' }],
                },
                {
                    type: NotebookNodeType.Query,
                    attrs: {
                        query: {
                            kind: 'InsightVizNode',
                            source: { kind: 'TrendsQuery', series: [] },
                        },
                    },
                },
            ],
        }
        const setLocalContent = jest.fn()

        openUpgradeToMarkdownNotebookDialog({ content, setLocalContent })

        expect(openDialogMock).toHaveBeenCalledTimes(1)
        const dialogProps = openDialogMock.mock.calls[0][0]

        expect(dialogProps.title).toEqual('Convert this notebook to Markdown notebooks?')
        expect(dialogProps.primaryButton.children).toEqual('Convert to Markdown notebooks')
        expect(dialogProps.secondaryButton.children).toEqual('Cancel')

        const { getByText } = render(createElement(Fragment, null, dialogProps.content))

        expect(getByText(/This conversion only works one way/)).toBeInstanceOf(HTMLElement)
        expect(getByText('Make sure you want to continue before converting it.')).toBeInstanceOf(HTMLElement)

        dialogProps.primaryButton.onClick()

        expect(setLocalContent).toHaveBeenCalledTimes(1)
        const convertedContent = setLocalContent.mock.calls[0][0]
        expect(isMarkdownNotebookContent(convertedContent)).toBe(true)
        expect(getMarkdownNotebookMarkdown(convertedContent)).toEqual(`# Activation

<Query query={{"kind":"InsightVizNode","source":{"kind":"TrendsQuery","series":[]}}} />`)
    })
})
