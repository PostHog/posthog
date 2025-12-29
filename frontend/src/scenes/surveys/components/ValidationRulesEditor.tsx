import { LemonCheckbox, LemonInput } from '@posthog/lemon-ui'

import { SurveyValidationRule, SurveyValidationType } from '~/types'

interface ValidationRulesEditorProps {
    value: SurveyValidationRule[] | undefined
    onChange: (rules: SurveyValidationRule[] | undefined) => void
}

export function ValidationRulesEditor({ value, onChange }: ValidationRulesEditorProps): JSX.Element {
    const rules = value || []

    const minLengthRule = rules.find((r) => r.type === SurveyValidationType.MinLength)
    const maxLengthRule = rules.find((r) => r.type === SurveyValidationType.MaxLength)
    const hasLengthLimit = !!minLengthRule || !!maxLengthRule

    const updateRules = (newRules: SurveyValidationRule[]): void => {
        onChange(newRules.length > 0 ? newRules : undefined)
    }

    const toggleLengthLimit = (enabled: boolean): void => {
        if (enabled) {
            const filtered = rules.filter(
                (r) => r.type !== SurveyValidationType.MinLength && r.type !== SurveyValidationType.MaxLength
            )
            updateRules([...filtered, { type: SurveyValidationType.MinLength, value: 1 }])
        } else {
            updateRules(
                rules.filter(
                    (r) => r.type !== SurveyValidationType.MinLength && r.type !== SurveyValidationType.MaxLength
                )
            )
        }
    }

    const setMinLength = (val: number | undefined): void => {
        const filtered = rules.filter((r) => r.type !== SurveyValidationType.MinLength)
        if (val && val > 0) {
            updateRules([...filtered, { type: SurveyValidationType.MinLength, value: val }])
        } else {
            updateRules(filtered)
        }
    }

    const setMaxLength = (val: number | undefined): void => {
        const filtered = rules.filter((r) => r.type !== SurveyValidationType.MaxLength)
        if (val && val > 0) {
            updateRules([...filtered, { type: SurveyValidationType.MaxLength, value: val }])
        } else {
            updateRules(filtered)
        }
    }

    return (
        <div className="flex flex-row items-center gap-2">
            <LemonCheckbox label="Validate message length" checked={hasLengthLimit} onChange={toggleLengthLimit} />
            <LemonInput
                type="number"
                min={1}
                max={maxLengthRule?.value}
                placeholder="Min"
                value={minLengthRule?.value}
                onChange={setMinLength}
                className="w-16"
                disabled={!hasLengthLimit}
            />
            <span className="text-secondary">to</span>
            <LemonInput
                type="number"
                min={minLengthRule?.value ?? 1}
                placeholder="Max"
                value={maxLengthRule?.value}
                onChange={setMaxLength}
                className="w-16"
                disabled={!hasLengthLimit}
            />
        </div>
    )
}
