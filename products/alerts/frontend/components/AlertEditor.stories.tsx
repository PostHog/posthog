import type { Meta, StoryObj } from '@storybook/react'
import { kea, path, useValues } from 'kea'
import { Form, forms } from 'kea-forms'
import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { AlertEditor, AlertEditorFormDetails, AlertEditorSection } from './AlertEditor'

const alertEditorStoryLogic = kea([
    path(['products', 'alerts', 'components', 'AlertEditor', 'story']),
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

interface AlertEditorStoryArgs {
    title: string
    description?: string
    isEditing: boolean
    isSubmitting: boolean
    hasChanges: boolean
    hasPendingChanges: boolean
    showBackButton: boolean
    showEnabledField: boolean
    showLeadingAction: boolean
}

function AlertEditorStory({
    title,
    description,
    isEditing,
    isSubmitting,
    hasChanges,
    hasPendingChanges,
    showBackButton,
    showEnabledField,
    showLeadingAction,
}: AlertEditorStoryArgs): JSX.Element {
    const { alertForm } = useValues(alertEditorStoryLogic)
    const [lastAction, setLastAction] = useState('No action selected')

    return (
        <div className="bg-default p-4">
            <Form
                logic={alertEditorStoryLogic}
                formKey="alertForm"
                enableFormOnSubmit
                className="h-[600px] max-w-[640px] overflow-hidden rounded border bg-surface-primary"
            >
                <AlertEditor
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
                </AlertEditor>
            </Form>
        </div>
    )
}

const meta: Meta<AlertEditorStoryArgs> = {
    title: 'Products/Alerts/Alert editor',
    args: {
        title: 'Edit alert',
        description: 'Get notified when a condition is met.',
        isEditing: true,
        isSubmitting: false,
        hasChanges: true,
        hasPendingChanges: false,
        showBackButton: true,
        showEnabledField: true,
        showLeadingAction: true,
    },
    render: (args) => <AlertEditorStory key={JSON.stringify(args)} {...args} />,
}

export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {}
