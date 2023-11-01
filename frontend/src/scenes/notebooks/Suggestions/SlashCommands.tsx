import { IconPlus } from 'lib/lemon-ui/icons'
import { InsertionSuggestion } from './InsertionSuggestion'
import { SlashCommandsPopover } from '../Notebook/SlashCommands'
import { LemonButton } from '@posthog/lemon-ui'
import { NotebookEditor } from '../Notebook/utils'
import { useState } from 'react'

const Component = ({ editor }: { editor: NotebookEditor }): JSX.Element => {
    const [visible, setVisible] = useState<boolean>(false)

    return (
        <SlashCommandsPopover
            mode="add"
            visible={visible}
            getPos={editor?.getCurrentPosition}
            onClose={() => setVisible(false)}
        >
            <LemonButton
                size="small"
                icon={<IconPlus />}
                className="NotebookFloatingButton__plus ml-1"
                onClick={() => setVisible(true)}
            />
        </SlashCommandsPopover>
    )
}

export default InsertionSuggestion.create({
    shouldShow: true,
    Component,
})
