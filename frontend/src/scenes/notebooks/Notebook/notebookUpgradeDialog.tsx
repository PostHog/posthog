import { JSONContent } from 'lib/components/RichContentEditor/types'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { buildMarkdownNotebookContent, convertNotebookContentToMarkdown } from './markdownNotebookV2'

type OpenUpgradeToMarkdownNotebookDialogProps = {
    content: JSONContent | null | undefined
    setLocalContent: (jsonContent: JSONContent) => void
}

export function openUpgradeToMarkdownNotebookDialog({
    content,
    setLocalContent,
}: OpenUpgradeToMarkdownNotebookDialogProps): void {
    LemonDialog.open({
        title: 'Convert this notebook to Markdown notebooks?',
        content: (
            <div className="text-sm text-secondary">
                <p>
                    This conversion only works one way. Once upgraded, this notebook cannot be converted back to the old
                    editor.
                </p>
                <p className="mt-2">Make sure you want to continue before converting it.</p>
            </div>
        ),
        primaryButton: {
            children: 'Convert to Markdown notebooks',
            type: 'primary',
            onClick: () => setLocalContent(buildMarkdownNotebookContent(convertNotebookContentToMarkdown(content))),
            size: 'small',
        },
        secondaryButton: {
            children: 'Cancel',
            type: 'tertiary',
            size: 'small',
        },
    })
}
