import { JSONContent } from 'lib/components/RichContentEditor/types'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import {
    buildMarkdownNotebookContent,
    convertNotebookContentToMarkdown,
    notebookContentHasCommentMarks,
} from './markdownNotebookV2'

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
                {notebookContentHasCommentMarks(content) && (
                    <p className="mt-2 font-semibold text-warning">
                        This notebook has inline comments. Their anchors are not carried over — the comments will no
                        longer point at the text they were left on.
                    </p>
                )}
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
