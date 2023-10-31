import { IconPlus } from 'lib/lemon-ui/icons'
import { InsertionSuggestion } from './InsertionSuggestion'
import { SlashCommandsPopover } from '../Notebook/SlashCommands'
import { LemonButton } from '@posthog/lemon-ui'
import { NotebookEditor } from '../Notebook/utils'
import { useActions, useValues } from 'kea'
import { notebookLogic } from '../Notebook/notebookLogic'

const Component = ({ editor }: { editor: NotebookEditor }): JSX.Element => {
    const { slashCommandsPopoverVisible } = useValues(notebookLogic)
    const { setSlashCommandsPopoverVisible } = useActions(notebookLogic)

    return (
        <SlashCommandsPopover
            mode="add"
            visible={slashCommandsPopoverVisible}
            getPos={editor?.getCurrentPosition}
            onClickOutside={() => setSlashCommandsPopoverVisible(false)}
        >
            <LemonButton
                size="small"
                icon={<IconPlus />}
                className="NotebookFloatingButton__plus ml-1"
                onClick={() => setSlashCommandsPopoverVisible(true)}
            />
        </SlashCommandsPopover>
    )
}

export default InsertionSuggestion.create({
    shouldShow: true,
    Component,
})
