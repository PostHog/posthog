import { useActions, useValues } from 'kea'

import { IconPlus, IconX } from '@posthog/icons'
import {
    Button,
    Field,
    FieldDescription,
    FieldError,
    FieldTitle,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    InputGroupText,
    Label,
    RadioGroup,
    RadioGroupItem,
    Text,
} from '@posthog/quill'

import { MAX_GUARDRAILS } from '../lib/betForm'
import { betFormLogic } from '../logics/betFormLogic'
import { BetInsightPicker } from './BetInsightPicker'

const DIRECTIONS = [
    { value: 'increase', label: 'Higher is better' },
    { value: 'decrease', label: 'Lower is better' },
]

export function BetGuardrailsField({ id }: { id: string }): JSX.Element {
    const { form, guardrailOptions, insightNames, fieldErrors, guardrailChips, guardrailSuggestionsLoading } =
        useValues(betFormLogic({ id }))
    const { addGuardrail, changeGuardrail, removeGuardrail, adoptGuardrail } = useActions(betFormLogic({ id }))
    const guardrails = form.secondary_metrics ?? []
    return (
        <Field>
            <FieldTitle>Guardrails (optional)</FieldTitle>
            <FieldDescription>Metrics that must not get worse while Bets tests ideas.</FieldDescription>
            {(guardrailSuggestionsLoading || guardrailChips.length > 0) && guardrails.length < MAX_GUARDRAILS && (
                <div className="Bets__guardrailChips" aria-busy={guardrailSuggestionsLoading || undefined}>
                    <span className="Bets__guardrailChipsLabel">
                        {guardrailSuggestionsLoading ? 'Finding guardrails…' : 'Suggested'}
                    </span>
                    {guardrailChips.map((option) => (
                        <Button
                            key={option.insight}
                            type="button"
                            size="sm"
                            variant="outline"
                            left
                            tooltip={option.definition}
                            onClick={() => adoptGuardrail(option)}
                            data-attr="bets-form-guardrail-chip"
                        >
                            <IconPlus />
                            {option.name}
                        </Button>
                    ))}
                </div>
            )}
            {guardrails.length > 0 && (
                <ul className="Bets__guardrails m-0 list-none p-0">
                    {guardrails.map((metric) => {
                        const name = insightNames[metric.insight] || metric.name || metric.insight
                        return (
                            <li
                                key={metric.insight}
                                className="Bets__guardrail"
                                data-guardrail={metric.insight}
                                data-undecided={metric.direction ? undefined : ''}
                            >
                                <div className="flex min-w-0 items-center gap-2">
                                    <span className="Bets__guardrailName min-w-0 flex-1 truncate" title={name}>
                                        {name}
                                    </span>
                                    <Button
                                        type="button"
                                        size="icon-sm"
                                        variant="default"
                                        aria-label={`Remove ${name}`}
                                        tooltip="Remove guardrail"
                                        onClick={() => removeGuardrail(metric.insight)}
                                        data-attr="bets-form-remove-guardrail"
                                    >
                                        <IconX />
                                    </Button>
                                </div>
                                <div className="Bets__guardrailControls">
                                    <RadioGroup
                                        className="flex w-auto flex-wrap gap-x-5 gap-y-2"
                                        value={metric.direction ?? null}
                                        onValueChange={(value: unknown) =>
                                            changeGuardrail(metric.insight, {
                                                direction: value === 'decrease' ? 'decrease' : 'increase',
                                            })
                                        }
                                        aria-label={`${name}: which way is better`}
                                    >
                                        {DIRECTIONS.map((option) => (
                                            <Label key={option.value} className="Bets__directionOption">
                                                <RadioGroupItem value={option.value} />
                                                {option.label}
                                            </Label>
                                        ))}
                                    </RadioGroup>
                                    {metric.direction ? (
                                        <div className="flex items-center gap-2">
                                            <Text size="xs" variant="muted" render={<span />}>
                                                May get worse by
                                            </Text>
                                            <InputGroup className="w-20">
                                                <InputGroupInput
                                                    inputMode="decimal"
                                                    value={String(
                                                        Math.round((metric.max_regression ?? 0.05) * 1000) / 10
                                                    )}
                                                    aria-label={`${name}: largest drop to allow, in percent`}
                                                    onChange={(event) => {
                                                        const value = Number(event.target.value)
                                                        if (Number.isFinite(value)) {
                                                            changeGuardrail(metric.insight, {
                                                                max_regression: Math.min(100, Math.max(0, value)) / 100,
                                                            })
                                                        }
                                                    }}
                                                />
                                                <InputGroupAddon align="inline-end">
                                                    <InputGroupText>%</InputGroupText>
                                                </InputGroupAddon>
                                            </InputGroup>
                                        </div>
                                    ) : (
                                        <Text size="xs" variant="muted" render={<span />}>
                                            Choose which way is better.
                                        </Text>
                                    )}
                                </div>
                            </li>
                        )
                    })}
                </ul>
            )}
            {fieldErrors.guardrails && <FieldError>{fieldErrors.guardrails}</FieldError>}
            {guardrails.length < MAX_GUARDRAILS && (
                <div>
                    <BetInsightPicker
                        compact
                        id={id}
                        value=""
                        options={guardrailOptions}
                        placeholder="Add a guardrail"
                        onSelect={(insight) => {
                            addGuardrail(insight)
                            window.setTimeout(() =>
                                document
                                    .querySelector<HTMLElement>(`[data-guardrail="${insight}"] [role=radio]`)
                                    ?.focus()
                            )
                        }}
                    />
                </div>
            )}
        </Field>
    )
}
