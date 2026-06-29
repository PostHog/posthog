export type BillingAlertNumericFormKey =
    | 'threshold_percentage'
    | 'threshold_value'
    | 'minimum_value'
    | 'baseline_window_days'
    | 'evaluation_delay_hours'
    | 'check_interval_hours'
    | 'cooldown_hours'

export interface BillingAlertNumberFieldConfig {
    key: Exclude<BillingAlertNumericFormKey, 'threshold_percentage' | 'threshold_value'>
    label: string
    min: number
    max?: number
    step?: number
    suffix?: string
    prefixSpend?: boolean
}

export const BILLING_ALERT_FORM_LIMITS: Record<
    BillingAlertNumericFormKey,
    { min: number; max?: number; step?: number }
> = {
    threshold_percentage: { min: 0.01, step: 0.01 },
    threshold_value: { min: 0 },
    minimum_value: { min: 0 },
    baseline_window_days: { min: 1, max: 90 },
    evaluation_delay_hours: { min: 0, max: 72 },
    check_interval_hours: { min: 1, max: 24 },
    cooldown_hours: { min: 0, max: 720 },
}

export const BILLING_ALERT_NUMBER_FIELDS: BillingAlertNumberFieldConfig[] = [
    { key: 'minimum_value', label: 'Minimum current value', min: 0, prefixSpend: true },
    { key: 'baseline_window_days', label: 'Baseline window', min: 1, max: 90, suffix: 'days' },
    { key: 'evaluation_delay_hours', label: 'Evaluation delay', min: 0, max: 72, suffix: 'hours' },
    { key: 'check_interval_hours', label: 'Check interval', min: 1, max: 24, suffix: 'hours' },
    { key: 'cooldown_hours', label: 'Cooldown', min: 0, max: 720, suffix: 'hours' },
]
