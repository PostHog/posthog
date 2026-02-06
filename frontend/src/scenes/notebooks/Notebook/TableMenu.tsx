import { BubbleMenu } from '@tiptap/react/menus'
import { useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { richContentEditorLogic } from 'lib/components/RichContentEditor/richContentEditorLogic'

export function TableMenu(): JSX.Element | null {
    const { ttEditor } = useValues(richContentEditorLogic)

    return (
        <BubbleMenu
            editor={ttEditor}
            shouldShow={({ editor }) => {
                return editor.isEditable && editor.isActive('table')
            }}
            options={{ placement: 'top-start' }}
        >
            <div className="NotebookTableMenu flex bg-surface-primary rounded border items-center text-secondary p-1 gap-x-0.5">
                <LemonButton
                    onClick={() => ttEditor.chain().focus().addRowBefore().run()}
                    icon={<IconPlus />}
                    size="small"
                    tooltip="Add row above"
                />
                <LemonButton
                    onClick={() => ttEditor.chain().focus().addRowAfter().run()}
                    icon={<IconPlus />}
                    size="small"
                    tooltip="Add row below"
                />
                <LemonDivider vertical />
                <LemonButton
                    onClick={() => ttEditor.chain().focus().addColumnBefore().run()}
                    icon={<IconPlus />}
                    size="small"
                    tooltip="Add column before"
                />
                <LemonButton
                    onClick={() => ttEditor.chain().focus().addColumnAfter().run()}
                    icon={<IconPlus />}
                    size="small"
                    tooltip="Add column after"
                />
                <LemonDivider vertical />
                <LemonButton
                    onClick={() => ttEditor.chain().focus().deleteRow().run()}
                    icon={<IconTrash />}
                    size="small"
                    tooltip="Delete row"
                />
                <LemonButton
                    onClick={() => ttEditor.chain().focus().deleteColumn().run()}
                    icon={<IconTrash />}
                    size="small"
                    tooltip="Delete column"
                />
                <LemonDivider vertical />
                <LemonButton
                    onClick={() => ttEditor.chain().focus().deleteTable().run()}
                    icon={<IconTrash />}
                    status="danger"
                    size="small"
                    tooltip="Delete table"
                />
            </div>
        </BubbleMenu>
    )
}
