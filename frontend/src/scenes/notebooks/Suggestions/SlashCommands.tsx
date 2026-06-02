import { useState } from 'react'

import { IconPlus, IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { insertNotebookAIPrompt } from '../Notebook/NotebookAIPrompt'
import { SlashCommandsPopover } from '../Notebook/SlashCommands'
import { InsertionSuggestion, InsertionSuggestionViewProps } from './InsertionSuggestion'

const Component = ({ editor }: InsertionSuggestionViewProps): JSX.Element => {
    const [visible, setVisible] = useState<boolean>(false)

    const onClick = (): void => {
        editor.focus()
        setVisible(true)
    }

    const onAIClick = (): void => {
        editor.focus()
        insertNotebookAIPrompt(editor, editor.getCurrentPosition())
    }

    return (
        <div className="flex items-center gap-1">
            <SlashCommandsPopover
                mode="add"
                visible={visible}
                getPos={editor?.getCurrentPosition}
                onClose={() => setVisible(false)}
            >
                <LemonButton size="xsmall" icon={<IconPlus />} tooltip="Add block" onClick={onClick} />
            </SlashCommandsPopover>
            <LemonButton
                size="xsmall"
                icon={<IconSparkles className="text-ai" />}
                tooltip="Ask PostHog AI"
                onClick={onAIClick}
            />
        </div>
    )
}

export default InsertionSuggestion.create({
    shouldShow: true,
    Component,
})
