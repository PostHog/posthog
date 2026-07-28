import type { ReactNode } from 'react'

import { IconCheckCircle, IconX } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { cn } from 'lib/utils/css-classes'

import type { UserBasicType } from '~/types'

export interface BillingAlertWizardStepDefinition<T extends string = string> {
    key: T
    label: string
}

export function BillingAlertChoiceCard({
    icon,
    name,
    description,
    onClick,
    selected,
}: {
    icon?: ReactNode
    name: string
    description: string
    onClick: () => void
    selected?: boolean
}): JSX.Element {
    return (
        <button
            type="button"
            onClick={onClick}
            aria-pressed={!!selected}
            className={cn(
                'group relative text-left rounded-lg border border-border bg-bg-light transition-all cursor-pointer p-5 w-full',
                'hover:border-border-bold hover:shadow-sm',
                'focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2',
                selected && 'border-border-bold shadow-sm'
            )}
        >
            <div className="flex items-center gap-4">
                {icon && <div className="shrink-0">{icon}</div>}
                <div>
                    <h3 className="font-semibold text-base mb-0.5 transition-colors group-hover:text-link">{name}</h3>
                    <p className="text-secondary text-sm mb-0">{description}</p>
                </div>
            </div>
        </button>
    )
}

export function BillingAlertWizardLayout<T extends string>({
    steps,
    currentStep,
    onStepClick,
    onCancel,
    children,
}: {
    steps: BillingAlertWizardStepDefinition<T>[]
    currentStep: T
    onStepClick: (step: T) => void
    onCancel: () => void
    children: ReactNode
}): JSX.Element {
    const currentOrder = steps.findIndex((step) => step.key === currentStep)

    return (
        <div className="flex flex-col min-h-[400px]">
            <div className="grid grid-cols-[1fr_auto_1fr] items-center">
                <div />
                <nav className="flex items-center justify-center" aria-label="Billing alert wizard progress">
                    {steps.map((step, index) => {
                        const isCompleted = currentOrder > index
                        const isCurrent = currentStep === step.key
                        const isFuture = index > currentOrder

                        return (
                            <div key={step.key} className="flex items-center">
                                {index > 0 && (
                                    <div
                                        className={cn(
                                            'w-6 h-px transition-colors duration-150',
                                            isCompleted || isCurrent ? 'bg-success' : 'bg-border-primary'
                                        )}
                                    />
                                )}
                                <button
                                    type="button"
                                    onClick={() => onStepClick(step.key)}
                                    disabled={isFuture}
                                    className={cn(
                                        'group flex items-center gap-1.5 px-2 py-1 rounded transition-all duration-150',
                                        'focus:outline-none focus-visible:ring-1 focus-visible:ring-accent',
                                        isFuture
                                            ? 'opacity-50 cursor-not-allowed'
                                            : 'hover:bg-fill-button-tertiary-hover active:scale-[0.98]'
                                    )}
                                    aria-current={isCurrent ? 'step' : undefined}
                                >
                                    {isCompleted ? (
                                        <IconCheckCircle className="size-5 text-success" />
                                    ) : (
                                        <span
                                            className={cn(
                                                'flex items-center justify-center size-5 rounded-full text-xs font-semibold',
                                                'transition-all duration-150',
                                                isCurrent && 'bg-accent text-primary-inverse ring-2 ring-accent/25',
                                                !isCurrent &&
                                                    'bg-surface-secondary text-secondary border border-primary'
                                            )}
                                        >
                                            {index + 1}
                                        </span>
                                    )}
                                    <span
                                        className={cn(
                                            'text-sm transition-colors duration-150',
                                            isCurrent && 'font-semibold text-primary',
                                            isCompleted && 'font-medium text-primary',
                                            !isCompleted && !isCurrent && 'text-secondary'
                                        )}
                                    >
                                        {step.label}
                                    </span>
                                </button>
                            </div>
                        )
                    })}
                </nav>
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconX />}
                    onClick={onCancel}
                    aria-label="Close billing alert wizard"
                    className="justify-self-start ml-2"
                />
            </div>
            <div className="max-w-lg mx-auto flex-1 w-full mt-4">{children}</div>
        </div>
    )
}

export function BillingAlertListToolbar({
    searchValue,
    onSearchChange,
    createdByValue,
    onCreatedByChange,
    showPaused,
    onShowPausedChange,
    createButton,
}: {
    searchValue: string
    onSearchChange: (value: string) => void
    createdByValue: string | number | null
    onCreatedByChange: (user: UserBasicType | null) => void
    showPaused: boolean
    onShowPausedChange: (checked: boolean | undefined) => void
    createButton: ReactNode
}): JSX.Element {
    return (
        <div className="flex gap-2 items-center">
            <LemonInput
                type="search"
                placeholder="Search billing alerts..."
                value={searchValue}
                onChange={onSearchChange}
            />
            <div className="flex-1" />
            <div className="flex flex-col xl:flex-row items-center gap-0.5 xl:gap-2 shrink-0">
                <span className="text-xs xl:text-sm">Created by:</span>
                <MemberSelect value={createdByValue} onChange={onCreatedByChange} />
            </div>
            <LemonCheckbox
                label="Show paused"
                bordered
                size="small"
                checked={showPaused}
                onChange={onShowPausedChange}
            />
            {createButton}
        </div>
    )
}
