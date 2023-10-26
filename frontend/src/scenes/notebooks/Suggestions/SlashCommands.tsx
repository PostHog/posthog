import { LemonButton } from '@posthog/lemon-ui'
import { IconPlus } from 'lib/lemon-ui/icons'
import { SlashCommandsPopover } from '../Notebook/SlashCommands'
import { InsertionSuggestion } from './InsertionSuggestion'
import { useState } from 'react'

const Component = (): JSX.Element => {
    const [visible, setVisible] = useState<boolean>(false)

    return (
        <SlashCommandsPopover mode="add" range={undefined} visible={visible}>
            <LemonButton
                size="small"
                onClick={() => setVisible(true)}
                icon={<IconPlus />}
                className="NotebookFloatingButton__plus ml-1"
            />
        </SlashCommandsPopover>
    )
}

export default InsertionSuggestion.create({
    shouldShow: true,
    Component,
})
