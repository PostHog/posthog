import { ReactNode } from 'react'

import { IconChevronLeft } from '@posthog/icons'
import { LemonCheckbox, LemonInput, SpinnerOverlay } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

interface AlertEditorModalProps {
    isOpen: boolean | undefined
    onClose?: () => void
    children: ReactNode
    width?: number
    loading?: boolean
    inline?: boolean
    closable?: boolean
}

export function AlertEditorModal({
    isOpen,
    onClose,
    children,
    width = 720,
    loading = false,
    inline = false,
    closable = true,
}: AlertEditorModalProps): JSX.Element {
    return (
        <LemonModal isOpen={isOpen} onClose={onClose} width={width} simple title="" inline={inline} closable={closable}>
            {loading ? <SpinnerOverlay /> : children}
        </LemonModal>
    )
}

interface AlertEditorModalLayoutProps {
    title: string
    description?: string
    onBack?: () => void
    children: ReactNode
    isEditing: boolean
    isSubmitting: boolean
    hasChanges: boolean
    hasPendingChanges?: boolean
    leadingActions?: ReactNode
    onSubmitAttempted?: () => void
}

export function AlertEditorModalLayout({
    title,
    description,
    onBack,
    children,
    isEditing,
    isSubmitting,
    hasChanges,
    hasPendingChanges = false,
    leadingActions,
    onSubmitAttempted,
}: AlertEditorModalLayoutProps): JSX.Element {
    const disabledReason = isEditing && !hasChanges && !hasPendingChanges ? 'No changes to save' : undefined

    return (
        <>
            <LemonModal.Header>
                <div className="flex items-center gap-2">
                    {onBack ? <LemonButton icon={<IconChevronLeft />} onClick={onBack} size="xsmall" /> : null}
                    <div>
                        <h3>{title}</h3>
                        {description ? <p className="text-muted text-sm m-0">{description}</p> : null}
                    </div>
                </div>
            </LemonModal.Header>
            <LemonModal.Content>{children}</LemonModal.Content>
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
        </>
    )
}

interface AlertEditorFormDetailsProps {
    enabled?: {
        checked: boolean
        dataAttr?: string
    }
    activity?: ReactNode
    nameDataAttr?: string
}

export function AlertEditorFormDetails({
    enabled,
    activity,
    nameDataAttr = 'alertForm-name',
}: AlertEditorFormDetailsProps): JSX.Element {
    return (
        <div className="space-y-4">
            <div className="flex gap-4 items-center">
                <LemonField className="flex-auto" name="name">
                    <LemonInput placeholder="Alert name" data-attr={nameDataAttr} />
                </LemonField>
                {enabled ? (
                    <LemonField name="enabled">
                        <LemonCheckbox
                            checked={enabled.checked}
                            data-attr={enabled.dataAttr}
                            fullWidth
                            label="Enabled"
                        />
                    </LemonField>
                ) : null}
            </div>
            {activity}
        </div>
    )
}

interface AlertEditorSectionProps {
    title: string
    description?: ReactNode
    children: ReactNode
}

export function AlertEditorSection({ title, description, children }: AlertEditorSectionProps): JSX.Element {
    return (
        <section className="space-y-3">
            <h3 className="text-base font-semibold m-0">{title}</h3>
            {description ? <p className="text-xs text-secondary m-0">{description}</p> : null}
            {children}
        </section>
    )
}
