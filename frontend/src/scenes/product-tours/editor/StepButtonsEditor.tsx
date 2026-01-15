import { LemonInput, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { ProductTourButtonAction, ProductTourStepButton, ProductTourStepButtons } from '~/types'

import { BUTTON_ACTION_OPTIONS, DEFAULT_PRIMARY_BUTTON, DEFAULT_SECONDARY_BUTTON } from '../productToursLogic'

interface ButtonEditorProps {
    button: ProductTourStepButton
    onChange: (button: ProductTourStepButton) => void
    label: string
}

function ButtonEditor({ button, onChange, label }: ButtonEditorProps): JSX.Element {
    return (
        <div className="space-y-2">
            <div className="flex items-center gap-3">
                <span className="text-xs font-medium text-muted w-16 shrink-0">{label}</span>
                <LemonInput
                    value={button.text}
                    onChange={(text) => onChange({ ...button, text })}
                    placeholder="Button text"
                    size="small"
                    className="flex-1"
                />
                <LemonSelect
                    value={button.action}
                    onChange={(action) => onChange({ ...button, action: action as ProductTourButtonAction })}
                    options={BUTTON_ACTION_OPTIONS}
                    size="small"
                />
            </div>
            {button.action === 'link' && (
                <div className="flex items-center gap-3">
                    <span className="w-16 shrink-0" />
                    <LemonInput
                        value={button.link ?? ''}
                        onChange={(link) => onChange({ ...button, link })}
                        placeholder="https://example.com"
                        size="small"
                        className="flex-1"
                    />
                </div>
            )}
        </div>
    )
}

export interface StepButtonsEditorProps {
    buttons: ProductTourStepButtons | undefined
    onChange: (buttons: ProductTourStepButtons) => void
}

export function StepButtonsEditor({ buttons, onChange }: StepButtonsEditorProps): JSX.Element {
    const primaryButton = buttons?.primary ?? DEFAULT_PRIMARY_BUTTON
    const secondaryButton = buttons?.secondary

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

    return (
        <div className="space-y-3">
            <ButtonEditor label="Primary" button={primaryButton} onChange={updatePrimaryButton} />
            {secondaryButton && (
                <ButtonEditor label="Secondary" button={secondaryButton} onChange={updateSecondaryButton} />
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
        </div>
    )
}
