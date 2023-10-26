import { IconPlus } from 'lib/lemon-ui/icons'
import { InsertionSuggestion } from './InsertionSuggestion'
import { SlashCommandsButtonPopover } from '../Notebook/SlashCommands'

const Component = (): JSX.Element => {
    return <SlashCommandsButtonPopover size="small" icon={<IconPlus />} className="NotebookFloatingButton__plus ml-1" />
}

export default InsertionSuggestion.create({
    shouldShow: true,
    Component,
})
