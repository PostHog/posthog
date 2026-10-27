import {
    Field,
    FieldDescription,
    FieldLabel,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import type {
    BetsModelOptionApi,
    BetsStepModelWriteApi,
    ModelStepEnumApi,
    StepBillingEnumApi,
} from '../generated/api.schemas'

const STEPS: Record<ModelStepEnumApi, { label: string; description: string }> = {
    scout: { label: 'Finding ideas', description: 'The Scout reads your data and code to pick the next idea.' },
    tracking: { label: 'Checking tracking', description: 'A task checks that the goal is measured in the code.' },
    idea: { label: 'Building ideas', description: 'A task writes the pull request and prepares the experiment.' },
}

const DEFAULT_MODEL = 'default'

export function BetStepModelField({
    step,
    value,
    options,
    planAvailable,
    disabled,
    onChange,
}: {
    step: ModelStepEnumApi
    value: BetsStepModelWriteApi | undefined
    options: BetsModelOptionApi[]
    planAvailable: boolean
    disabled: boolean
    onChange: (patch: Partial<BetsStepModelWriteApi>) => void
}): JSX.Element {
    const selected = options.find((option) => option.model === value?.model)
    const models = [
        { value: DEFAULT_MODEL, label: 'Project default' },
        ...options.map((option) => ({
            value: option.model,
            label: option.cost_multiplier ? `${option.label} · ${option.cost_multiplier}` : option.label,
        })),
    ]
    const efforts = (selected?.supported_efforts ?? []).map((effort) => ({ value: effort, label: effort }))
    const planUsable = planAvailable && (!selected || selected.runtime_adapter === 'codex')
    const billing: { value: StepBillingEnumApi; label: string }[] = [
        { value: 'credits', label: 'PostHog credits' },
        ...(planUsable ? [{ value: 'subscription' as const, label: 'ChatGPT plan' }] : []),
    ]
    const id = `bets-model-${step}`
    return (
        <div className="flex flex-col gap-2">
            <div className="Bets__formRow">
                <Field>
                    <FieldLabel htmlFor={id}>{STEPS[step].label}</FieldLabel>
                    <Select
                        value={value?.model || DEFAULT_MODEL}
                        items={models}
                        disabled={disabled}
                        onValueChange={(model) =>
                            onChange({
                                model: !model || model === DEFAULT_MODEL ? '' : model,
                                reasoning_effort:
                                    options.find((option) => option.model === model)?.supported_efforts[0] ?? '',
                                billing:
                                    options.find((option) => option.model === model)?.runtime_adapter === 'codex' ||
                                    model === DEFAULT_MODEL
                                        ? value?.billing
                                        : 'credits',
                            })
                        }
                    >
                        <SelectTrigger id={id} aria-label={`${STEPS[step].label} model`}>
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {models.map((model) => (
                                <SelectItem key={model.value} value={model.value}>
                                    {model.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </Field>
                <div className="Bets__formRow">
                    {!!efforts.length && (
                        <Field>
                            <FieldLabel htmlFor={`${id}-effort`}>Effort</FieldLabel>
                            <Select
                                value={value?.reasoning_effort || efforts[0].value}
                                items={efforts}
                                disabled={disabled}
                                onValueChange={(effort) => effort && onChange({ reasoning_effort: effort })}
                            >
                                <SelectTrigger id={`${id}-effort`} aria-label={`${STEPS[step].label} effort`}>
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    {efforts.map((effort) => (
                                        <SelectItem key={effort.value} value={effort.value}>
                                            {effort.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </Field>
                    )}
                    <Field>
                        <FieldLabel htmlFor={`${id}-billing`}>Billing</FieldLabel>
                        <Select
                            value={planUsable ? (value?.billing ?? 'credits') : 'credits'}
                            items={billing}
                            disabled={disabled || billing.length < 2}
                            onValueChange={(choice) => choice && onChange({ billing: choice as StepBillingEnumApi })}
                        >
                            <SelectTrigger id={`${id}-billing`} aria-label={`${STEPS[step].label} billing`}>
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {billing.map((choice) => (
                                    <SelectItem key={choice.value} value={choice.value}>
                                        {choice.label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </Field>
                </div>
            </div>
            <FieldDescription>
                {STEPS[step].description}
                {!planAvailable && ' Connect a ChatGPT plan in PostHog Desktop to bill a step to your plan.'}
            </FieldDescription>
        </div>
    )
}
