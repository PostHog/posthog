import { IconPlus } from 'lib/lemon-ui/icons'
import { InsertionSuggestion, InsertionSuggestionViewProps } from './InsertionSuggestion'
import { SlashCommandsPopover } from '../Notebook/SlashCommands'
import { LemonButton } from '@posthog/lemon-ui'
import { useState } from 'react'

const Component = ({ editor }: InsertionSuggestionViewProps): JSX.Element => {
    const [visible, setVisible] = useState<boolean>(false)

    const onClick = (): void => {
        editor.focus()
        setVisible(true)
    }

    return (
        <SlashCommandsPopover
            mode="add"
            visible={visible}
            getPos={editor?.getCurrentPosition}
            onClose={() => setVisible(false)}
        >
            <LemonButton size="xsmall" icon={<IconPlus />} onClick={onClick} />
        </SlashCommandsPopover>
    )
}

export default InsertionSuggestion.create({
    shouldShow: true,
    Component,
})
