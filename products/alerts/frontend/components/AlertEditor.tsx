import { ReactNode } from 'react'

import { IconChevronLeft } from '@posthog/icons'
import { LemonCheckbox, LemonInput, LemonSkeleton } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { cn } from 'lib/utils/css-classes'

export interface AlertEditorHeaderProps {
    title: string
    description?: string
    onBack?: () => void
}

export function AlertEditorHeader({ title, description, onBack }: AlertEditorHeaderProps): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            {onBack ? (
                <LemonButton
                    icon={<IconChevronLeft />}
                    onClick={onBack}
                    size="xsmall"
                    tooltip="Go back"
                    aria-label="Go back"
                />
            ) : null}
            <div>
                <h3 className="text-lg font-bold m-0">{title}</h3>
                {description ? <p className="text-muted text-sm mt-2 mb-0">{description}</p> : null}
            </div>
        </div>
    )
}

export function AlertEditorLoading({ title, onBack }: Pick<AlertEditorHeaderProps, 'title' | 'onBack'>): JSX.Element {
    return (
        <div className="flex min-h-[600px] flex-col" aria-busy="true" aria-label={`Loading ${title.toLowerCase()}`}>
            <header className="border-b p-4">
                <AlertEditorHeader title={title} onBack={onBack} />
            </header>
            <div className="flex-1 space-y-4 p-4">
                <LemonSkeleton className="h-20 w-full" />
                <LemonSkeleton className="h-10 w-full" />
                <LemonSkeleton className="h-4 w-48" />
                <div className="grid grid-cols-2 gap-8">
                    <div className="space-y-3">
                        <LemonSkeleton className="h-10 w-full" />
                        <LemonSkeleton className="h-5 w-4/5" />
                    </div>
                    <div className="space-y-3">
                        <LemonSkeleton className="h-10 w-full" />
                        <LemonSkeleton className="h-10 w-3/4" />
                    </div>
                </div>
            </div>
            <footer className="flex items-center justify-between border-t p-4">
                <div className="flex gap-2">
                    <LemonSkeleton className="h-10 w-28" />
                    <LemonSkeleton className="h-10 w-32" />
                </div>
                <LemonSkeleton className="h-10 w-20" />
            </footer>
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
    showNoChangesLabel?: boolean
}

export function AlertEditorActions({
    isEditing,
    isSubmitting,
    hasChanges,
    hasPendingChanges = false,
    leadingActions,
    onSubmitAttempted,
    showNoChangesLabel = false,
}: AlertEditorActionsProps): JSX.Element {
    const hasUnsavedChanges = hasChanges || hasPendingChanges
    const disabledReason = isEditing && !hasUnsavedChanges ? 'No changes to save' : undefined
    let buttonLabel = 'Create alert'
    if (isEditing) {
        buttonLabel = showNoChangesLabel && !hasUnsavedChanges ? 'No changes' : 'Save'
    }

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
                {buttonLabel}
            </LemonButton>
        </>
    )
}

export interface AlertEditorProps extends AlertEditorHeaderProps, AlertEditorActionsProps {
    children: ReactNode
    className?: string
    contentClassName?: string
}

export function AlertEditor({
    title,
    description,
    onBack,
    children,
    className,
    contentClassName,
    ...actionsProps
}: AlertEditorProps): JSX.Element {
    return (
        <div className={cn('flex flex-col', className)}>
            <header className="border-b p-4">
                <AlertEditorHeader title={title} description={description} onBack={onBack} />
            </header>
            <section className={cn('p-4', contentClassName)}>{children}</section>
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
    nameError?: string
}

export function AlertEditorFormDetails({
    enabled,
    activity,
    nameDataAttr = 'alertForm-name',
    nameError,
}: AlertEditorFormDetailsProps): JSX.Element {
    return (
        <div className="space-y-2">
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
            {nameError ? <LemonField.Error error={nameError} /> : null}
            {activity}
        </div>
    )
}

interface AlertEditorSectionProps {
    title: string
    icon?: ReactNode
    description?: ReactNode
    children: ReactNode
}

export function AlertEditorSection({ title, icon, description, children }: AlertEditorSectionProps): JSX.Element {
    return (
        <section className="space-y-2.5">
            <div className="space-y-0.5">
                <h3 className="text-sm font-semibold m-0 flex items-center gap-1.5">
                    {icon ? <span className="text-muted">{icon}</span> : null}
                    {title}
                </h3>
                {description ? <p className="text-xs text-secondary m-0">{description}</p> : null}
            </div>
            {children}
        </section>
    )
}
