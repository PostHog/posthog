import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { AlertEditorModalFooter, AlertEditorModalHeader } from './AlertEditorModal'

interface AlertEditorModalStoryArgs {
    title: string
    description?: string
    isEditing: boolean
    isSubmitting: boolean
    hasChanges: boolean
    hasPendingChanges: boolean
    showBackButton: boolean
    showLeadingAction: boolean
}

function AlertEditorModalStory({
    title,
    description,
    isEditing,
    isSubmitting,
    hasChanges,
    hasPendingChanges,
    showBackButton,
    showLeadingAction,
}: AlertEditorModalStoryArgs): JSX.Element {
    const [lastAction, setLastAction] = useState('No action selected')

    return (
        <div className="bg-default p-4">
            <LemonModal isOpen inline simple closable={false} width={640}>
                <form
                    className="LemonModal__layout"
                    onSubmit={(event) => {
                        event.preventDefault()
                        setLastAction(isEditing ? 'Saved alert' : 'Created alert')
                    }}
                >
                    <AlertEditorModalHeader
                        title={title}
                        description={description}
                        onBack={showBackButton ? () => setLastAction('Selected back') : undefined}
                    />
                    <LemonModal.Content>
                        <div className="deprecated-space-y-2">
                            <p className="m-0">Product-specific alert fields render here.</p>
                            <p className="text-muted m-0">{lastAction}</p>
                        </div>
                    </LemonModal.Content>
                    <AlertEditorModalFooter
                        isEditing={isEditing}
                        isSubmitting={isSubmitting}
                        hasChanges={hasChanges}
                        hasPendingChanges={hasPendingChanges}
                        leadingActions={
                            showLeadingAction ? (
                                <LemonButton type="secondary" onClick={() => setLastAction('Selected delete')}>
                                    Delete alert
                                </LemonButton>
                            ) : undefined
                        }
                    />
                </form>
            </LemonModal>
        </div>
    )
}

const meta: Meta<AlertEditorModalStoryArgs> = {
    title: 'Components/Alerts/Alert editor modal',
    args: {
        title: 'New alert',
        description: 'Get notified when a condition is met.',
        isEditing: false,
        isSubmitting: false,
        hasChanges: false,
        hasPendingChanges: false,
        showBackButton: true,
        showLeadingAction: false,
    },
    render: (args) => <AlertEditorModalStory key={JSON.stringify(args)} {...args} />,
}

export default meta

type Story = StoryObj<typeof meta>

export const Create: Story = {}

export const EditWithChanges: Story = {
    args: {
        title: 'Edit alert',
        isEditing: true,
        hasChanges: true,
        showLeadingAction: true,
    },
}

export const EditWithoutChanges: Story = {
    args: {
        title: 'Edit alert',
        isEditing: true,
        showLeadingAction: true,
    },
}

export const EditWithPendingChanges: Story = {
    args: {
        title: 'Edit alert',
        isEditing: true,
        hasPendingChanges: true,
        showLeadingAction: true,
    },
}

export const Submitting: Story = {
    args: {
        isSubmitting: true,
    },
}
