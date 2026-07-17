import { ReactNode } from 'react'

import { IconChevronLeft } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

interface AlertEditorModalHeaderProps {
    title: string
    description?: string
    onBack?: () => void
}

export function AlertEditorModalHeader({ title, description, onBack }: AlertEditorModalHeaderProps): JSX.Element {
    return (
        <LemonModal.Header>
            <div className="flex items-center gap-2">
                {onBack ? <LemonButton icon={<IconChevronLeft />} onClick={onBack} size="xsmall" /> : null}
                <div>
                    <h3>{title}</h3>
                    {description ? <p className="text-muted text-sm m-0">{description}</p> : null}
                </div>
            </div>
        </LemonModal.Header>
    )
}

interface AlertEditorModalFooterProps {
    isEditing: boolean
    isSubmitting: boolean
    hasChanges: boolean
    hasPendingChanges?: boolean
    leadingActions?: ReactNode
    onSubmitAttempted?: () => void
}

export function AlertEditorModalFooter({
    isEditing,
    isSubmitting,
    hasChanges,
    hasPendingChanges = false,
    leadingActions,
    onSubmitAttempted,
}: AlertEditorModalFooterProps): JSX.Element {
    const disabledReason = isEditing && !hasChanges && !hasPendingChanges ? 'No changes to save' : undefined

    return (
        <LemonModal.Footer>
            {leadingActions ? <div className="flex-1">{leadingActions}</div> : null}
            <LemonButton
                type="primary"
                htmlType="submit"
                loading={isSubmitting}
                disabledReason={disabledReason}
                onClick={onSubmitAttempted}
            >
                {isEditing ? 'Save' : 'Create alert'}
            </LemonButton>
        </LemonModal.Footer>
    )
}
