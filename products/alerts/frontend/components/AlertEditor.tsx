import clsx from 'clsx'
import { ReactNode } from 'react'

import { IconChevronLeft } from '@posthog/icons'
import { LemonCheckbox, LemonInput } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'

export interface AlertEditorHeaderProps {
    title: string
    description?: string
    onBack?: () => void
}

export function AlertEditorHeader({ title, description, onBack }: AlertEditorHeaderProps): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            {onBack ? <LemonButton icon={<IconChevronLeft />} onClick={onBack} size="xsmall" /> : null}
            <div>
                <h3 className="text-lg font-bold m-0">{title}</h3>
                {description ? <p className="text-muted text-sm mt-2 mb-0">{description}</p> : null}
            </div>
        </div>
    )
}

export interface AlertEditorActionsProps {
    isEditing: boolean
    isSubmitting: boolean
    hasChanges: boolean
    hasPendingChanges?: boolean
    leadingActions?: ReactNode
    onSubmitAttempted?: () => void
}

export function AlertEditorActions({
    isEditing,
    isSubmitting,
    hasChanges,
    hasPendingChanges = false,
    leadingActions,
    onSubmitAttempted,
}: AlertEditorActionsProps): JSX.Element {
    const disabledReason = isEditing && !hasChanges && !hasPendingChanges ? 'No changes to save' : undefined

    return (
        <>
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
        </>
    )
}

export interface AlertEditorProps extends AlertEditorHeaderProps, AlertEditorActionsProps {
    children: ReactNode
    className?: string
}

export function AlertEditor({
    title,
    description,
    onBack,
    children,
    className,
    ...actionsProps
}: AlertEditorProps): JSX.Element {
    return (
        <div className={clsx('flex h-full min-h-0 flex-col overflow-hidden', className)}>
            <header className="border-b p-4">
                <AlertEditorHeader title={title} description={description} onBack={onBack} />
            </header>
            <section className="min-h-0 flex-1 overflow-y-auto p-4">{children}</section>
            <footer className="flex flex-wrap items-center justify-end gap-2 border-t p-4">
                <AlertEditorActions {...actionsProps} />
            </footer>
        </div>
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
