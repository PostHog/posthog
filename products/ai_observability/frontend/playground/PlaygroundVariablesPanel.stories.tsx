import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { llmPlaygroundPromptsLogic } from './llmPlaygroundPromptsLogic'
import { llmPlaygroundVariablesLogic } from './llmPlaygroundVariablesLogic'
import { PlaygroundVariablesPanel } from './PlaygroundVariablesPanel'

const meta: Meta<typeof PlaygroundVariablesPanel> = {
    title: 'Components/Playground Variables Panel',
    component: PlaygroundVariablesPanel,
}
export default meta
type Story = StoryObj<typeof PlaygroundVariablesPanel>

export const FilledAndUnfilledVariables: Story = {
    render: function Render() {
        const { setSystemPrompt } = useActions(llmPlaygroundPromptsLogic)
        const { setVariableValue } = useActions(llmPlaygroundVariablesLogic)
        useEffect(() => {
            setSystemPrompt('You are a helpful assistant for {{company}}. Write about {{topic}}.')
            setVariableValue('company', 'Hedgebox')
            // oxlint-disable-next-line exhaustive-deps
        }, [])
        return (
            <div className="max-w-150">
                <PlaygroundVariablesPanel />
            </div>
        )
    },
}
