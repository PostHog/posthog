import { BubbleMenu } from '@tiptap/react/menus'
import { useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { richContentEditorLogic } from 'lib/components/RichContentEditor/richContentEditorLogic'

export function TableMenu(): JSX.Element | null {
    const { ttEditor } = useValues(richContentEditorLogic)

    if (!ttEditor) {
        return null
    }

    return (
        <BubbleMenu
            editor={ttEditor}
            shouldShow={({ editor }) => {
                return editor.isEditable && editor.isActive('table')
            }}
            options={{ placement: 'top-start' }}
        >
            <div className="NotebookTableMenu flex bg-surface-primary rounded border items-center text-secondary p-1 gap-x-0.5 text-xs">
                <LemonButton onClick={() => ttEditor.chain().focus().addRowBefore().run()} size="small">
                    Add row above
                </LemonButton>
                <LemonButton onClick={() => ttEditor.chain().focus().addRowAfter().run()} size="small">
                    Add row below
                </LemonButton>
                <LemonDivider vertical />
                <LemonButton onClick={() => ttEditor.chain().focus().addColumnBefore().run()} size="small">
                    Add column left
                </LemonButton>
                <LemonButton onClick={() => ttEditor.chain().focus().addColumnAfter().run()} size="small">
                    Add column right
                </LemonButton>
                <LemonDivider vertical />
                <LemonButton onClick={() => ttEditor.chain().focus().deleteRow().run()} size="small" status="danger">
                    Delete row
                </LemonButton>
                <LemonButton onClick={() => ttEditor.chain().focus().deleteColumn().run()} size="small" status="danger">
                    Delete column
                </LemonButton>
                <LemonDivider vertical />
                <LemonButton
                    onClick={() => ttEditor.chain().focus().deleteTable().run()}
                    icon={<IconTrash />}
                    status="danger"
                    size="small"
                    tooltip="Delete entire table"
                />
            </div>
        </BubbleMenu>
    )
}
