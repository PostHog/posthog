import { LemonInput, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { ProductTourButtonAction, ProductTourStepButton, ProductTourStepButtons } from '~/types'

import { TourSelector } from '../components/TourSelector'
import {
    BUTTON_ACTION_OPTIONS,
    DEFAULT_PRIMARY_BUTTON,
    DEFAULT_SECONDARY_BUTTON,
    TOUR_BUTTON_ACTION_OPTIONS,
    getDefaultTourStepButtons,
} from '../productToursLogic'

interface ButtonEditorProps {
    button: ProductTourStepButton
    onChange: (button: ProductTourStepButton) => void
    label: string
    isTourContext?: boolean
    stepIndex?: number
    totalSteps?: number
}

function ButtonEditor({
    button,
    onChange,
    label,
    isTourContext = false,
    stepIndex = 0,
    totalSteps = 1,
}: ButtonEditorProps): JSX.Element {
    const actionOptions = isTourContext ? TOUR_BUTTON_ACTION_OPTIONS : BUTTON_ACTION_OPTIONS

    const actionDisabledReason = (action: ProductTourButtonAction): string | undefined => {
        if (action === 'next_step' && stepIndex === totalSteps - 1) {
            return 'No further tour steps'
        }
        if (action === 'previous_step' && stepIndex === 0) {
            return 'No previous tour steps'
        }
    }

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-3">
                <span className={`text-xs font-medium text-muted w-16 shrink-0 ${!label ? 'hidden' : ''}`}>
                    {label}
                </span>
                <LemonInput
                    value={button.text}
                    onChange={(text) => onChange({ ...button, text })}
                    placeholder="Button text"
                    size="small"
                    className="flex-1"
                />
                <LemonSelect
                    value={button.action}
                    onChange={(action) => {
                        const newAction = action as ProductTourButtonAction
                        onChange({
                            ...button,
                            action: newAction,
                            link: newAction === 'link' ? button.link : undefined,
                            tourId: newAction === 'trigger_tour' ? button.tourId : undefined,
                        })
                    }}
                    options={actionOptions.map((opt) => ({
                        ...opt,
                        disabledReason: actionDisabledReason(opt.value),
                    }))}
                    size="small"
                />
            </div>
            {button.action === 'link' && (
                <div className="flex items-center gap-3">
                    <span className={`w-16 shrink-0 ${!label ? 'hidden' : ''}`} />
                    <LemonInput
                        value={button.link ?? ''}
                        onChange={(link) => onChange({ ...button, link })}
                        placeholder="https://example.com"
                        size="small"
                        className="flex-1"
                    />
                </div>
            )}
            {button.action === 'trigger_tour' && (
                <div className="flex items-center gap-3">
                    <span className={`w-16 shrink-0 ${!label ? 'hidden' : ''}`} />
                    <TourSelector
                        value={button.tourId}
                        onChange={(tourId) => onChange({ ...button, tourId })}
                        className="flex-1"
                    />
                </div>
            )}
        </div>
    )
}

export interface StepButtonsEditorProps {
    buttons: ProductTourStepButtons | undefined
    onChange: (buttons: ProductTourStepButtons | undefined) => void
    isTourContext?: boolean
    stepIndex?: number
    totalSteps?: number
    layout?: 'stacked' | 'horizontal'
}

export function StepButtonsEditor({
    buttons,
    onChange,
    isTourContext = false,
    stepIndex = 0,
    totalSteps = 1,
    layout = 'stacked',
}: StepButtonsEditorProps): JSX.Element {
    const customButtonsEnabled = !!buttons
    const primaryButton = buttons?.primary ?? DEFAULT_PRIMARY_BUTTON
    const secondaryButton = buttons?.secondary

    const toggleCustomButtons = (enabled: boolean): void => {
        if (enabled) {
            onChange(
                isTourContext ? getDefaultTourStepButtons(stepIndex, totalSteps) : { primary: DEFAULT_PRIMARY_BUTTON }
            )
        } else {
            onChange(undefined)
        }
    }

    const updatePrimaryButton = (button: ProductTourStepButton): void => {
        onChange({
            ...buttons,
            primary: button,
        })
    }

    const updateSecondaryButton = (button: ProductTourStepButton): void => {
        onChange({
            ...buttons,
            secondary: button,
        })
    }

    const toggleSecondaryButton = (enabled: boolean): void => {
        onChange({
            ...buttons,
            secondary: enabled ? DEFAULT_SECONDARY_BUTTON : undefined,
        })
    }

    if (layout === 'horizontal') {
        return (
            <div className="space-y-3">
                {isTourContext && (
                    <LemonSwitch checked={customButtonsEnabled} onChange={toggleCustomButtons} label="Custom buttons" />
                )}
                {(customButtonsEnabled || !isTourContext) && (
                    <div className="flex gap-4">
                        <div className="flex-1 space-y-2">
                            <div className="text-xs font-medium text-muted">Primary</div>
                            <ButtonEditor
                                label=""
                                button={primaryButton}
                                onChange={updatePrimaryButton}
                                isTourContext={isTourContext}
                                stepIndex={stepIndex}
                                totalSteps={totalSteps}
                            />
                        </div>
                        <div className="flex-1 space-y-2">
                            <div className="flex items-center justify-between">
                                <span className="text-xs font-medium text-muted">Secondary</span>
                                <LemonSwitch
                                    checked={!!secondaryButton}
                                    onChange={toggleSecondaryButton}
                                    size="small"
                                />
                            </div>
                            {secondaryButton ? (
                                <ButtonEditor
                                    label=""
                                    button={secondaryButton}
                                    onChange={updateSecondaryButton}
                                    isTourContext={isTourContext}
                                    stepIndex={stepIndex}
                                    totalSteps={totalSteps}
                                />
                            ) : (
                                <div className="text-muted text-sm py-2">No secondary button</div>
                            )}
                        </div>
                    </div>
                )}
            </div>
        )
    }

    return (
        <div className="space-y-3">
            {isTourContext && (
                <LemonSwitch checked={customButtonsEnabled} onChange={toggleCustomButtons} label="Custom buttons" />
            )}
            {(customButtonsEnabled || !isTourContext) && (
                <>
                    <ButtonEditor
                        label="Primary"
                        button={primaryButton}
                        onChange={updatePrimaryButton}
                        isTourContext={isTourContext}
                        stepIndex={stepIndex}
                        totalSteps={totalSteps}
                    />
                    {secondaryButton && (
                        <ButtonEditor
                            label="Secondary"
                            button={secondaryButton}
                            onChange={updateSecondaryButton}
                            isTourContext={isTourContext}
                            stepIndex={stepIndex}
                            totalSteps={totalSteps}
                        />
                    )}
                    <div className="flex items-center gap-3">
                        <span className="w-16 shrink-0" />
                        <LemonSwitch
                            checked={!!secondaryButton}
                            onChange={toggleSecondaryButton}
                            label="Secondary button"
                            size="small"
                        />
                    </div>
                </>
            )}
        </div>
    )
}
