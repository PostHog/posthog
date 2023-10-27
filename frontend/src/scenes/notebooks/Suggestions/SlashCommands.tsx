import { IconPlus } from 'lib/lemon-ui/icons'
import { InsertionSuggestion } from './InsertionSuggestion'
import { SlashCommandsPopover } from '../Notebook/SlashCommands'
import { useState } from 'react'
import { LemonButton } from '@posthog/lemon-ui'

const Component = (): JSX.Element => {
    const [visible, setVisible] = useState<boolean>(false)

    return (
        <SlashCommandsPopover mode="add" visible={visible} onClickOutside={() => setVisible(false)}>
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
