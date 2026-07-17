import type { Meta, StoryObj } from '@storybook/react'
import { kea, path, useValues } from 'kea'
import { Form, forms } from 'kea-forms'
import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import {
    AlertEditorFormDetails,
    AlertEditorModal,
    AlertEditorModalLayout,
    AlertEditorSection,
} from './AlertEditorModal'

const alertEditorStoryLogic = kea([
    path(['products', 'alerts', 'components', 'AlertEditorModal', 'story']),
    forms({
        alertForm: {
            defaults: {
                name: 'Error rate alert',
                enabled: true,
            },
            submit: () => Promise.resolve(),
        },
    }),
])

interface AlertEditorModalStoryArgs {
    title: string
    description?: string
    isEditing: boolean
    isSubmitting: boolean
    hasChanges: boolean
    hasPendingChanges: boolean
    loading: boolean
    showBackButton: boolean
    showEnabledField: boolean
    showLeadingAction: boolean
}

function AlertEditorModalStory({
    title,
    description,
    isEditing,
    isSubmitting,
    hasChanges,
    hasPendingChanges,
    loading,
    showBackButton,
    showEnabledField,
    showLeadingAction,
}: AlertEditorModalStoryArgs): JSX.Element {
    const { alertForm } = useValues(alertEditorStoryLogic)
    const [lastAction, setLastAction] = useState('No action selected')

    return (
        <div className="bg-default p-4">
            <AlertEditorModal isOpen inline closable={false} width={640} loading={loading}>
                <Form
                    logic={alertEditorStoryLogic}
                    formKey="alertForm"
                    enableFormOnSubmit
                    className="LemonModal__layout"
                >
                    <AlertEditorModalLayout
                        title={title}
                        description={description}
                        onBack={showBackButton ? () => setLastAction('Selected back') : undefined}
                        isEditing={isEditing}
                        isSubmitting={isSubmitting}
                        hasChanges={hasChanges}
                        hasPendingChanges={hasPendingChanges}
                        onSubmitAttempted={() => setLastAction(isEditing ? 'Saved alert' : 'Created alert')}
                        leadingActions={
                            showLeadingAction ? (
                                <LemonButton type="secondary" onClick={() => setLastAction('Selected delete')}>
                                    Delete alert
                                </LemonButton>
                            ) : undefined
                        }
                    >
                        <div className="space-y-6">
                            <AlertEditorFormDetails
                                enabled={showEnabledField ? { checked: alertForm.enabled } : undefined}
                                activity={<p className="text-muted text-sm m-0">Created by Story User</p>}
                            />
                            <AlertEditorSection
                                title="Definition"
                                description="Product-specific alert conditions render inside shared sections."
                            >
                                <div className="border rounded p-3 text-sm">Alert when the error rate exceeds 5%.</div>
                            </AlertEditorSection>
                            <AlertEditorSection title="Notification">
                                <div className="border rounded p-3 text-sm">Send a notification to #alerts.</div>
                            </AlertEditorSection>
                            <p className="text-muted m-0">{lastAction}</p>
                        </div>
                    </AlertEditorModalLayout>
                </Form>
            </AlertEditorModal>
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
        loading: false,
        showBackButton: true,
        showEnabledField: true,
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

export const Loading: Story = {
    args: {
        loading: true,
    },
}
