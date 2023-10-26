import { IconPlus } from 'lib/lemon-ui/icons'
import { SlashCommandsButtonPopover } from '../Notebook/SlashCommands'
import { InsertionSuggestion } from './InsertionSuggestion'

const Component = (): JSX.Element => {
    return <SlashCommandsButtonPopover size="small" icon={<IconPlus />} className="NotebookFloatingButton__plus ml-1" />
}

export default InsertionSuggestion.create({
    shouldShow: true,
    Component,
})
