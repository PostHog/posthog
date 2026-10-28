import { useActions, useValues } from 'kea'

import {
    Field,
    FieldDescription,
    FieldError,
    FieldLabel,
    FieldTitle,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    InputGroupText,
    Label,
    RadioGroup,
    RadioGroupItem,
    Skeleton,
    Text,
} from '@posthog/quill'

import { formatMeasure } from '../lib/insightMetric'
import { betFormLogic } from '../logics/betFormLogic'

export function BetTargetField({ id }: { id: string }): JSX.Element {
    const { form, current, display, previewLoading, unit, targetChange, direction, needsDirection, fieldErrors } =
        useValues(betFormLogic({ id }))
    const { change, touch } = useActions(betFormLogic({ id }))
    const prefix = form.goal_insight ? display.prefix : ''
    const changeText =
        targetChange === null
            ? null
            : `${new Intl.NumberFormat('en-US', { style: 'percent', maximumFractionDigits: 1 }).format(Math.abs(targetChange))} ${
                  targetChange > 0 ? 'higher' : 'lower'
              } than now`
    return (
        <div className="flex flex-col gap-4">
            <div className="Bets__measureRow">
                <Field>
                    <FieldLabel>Now</FieldLabel>
                    <div className="Bets__nowValue" aria-live="polite">
                        {!form.goal_insight ? (
                            <Text size="xs" variant="muted">
                                Choose an insight first
                            </Text>
                        ) : previewLoading ? (
                            <Skeleton className="h-5 w-16" />
                        ) : current === null ? (
                            <Text size="xs" variant="muted">
                                No value yet
                            </Text>
                        ) : (
                            <span className="Bets__nowNumber">{formatMeasure(current, display)}</span>
                        )}
                    </div>
                </Field>
                <Field data-invalid={!!fieldErrors.target || undefined}>
                    <FieldLabel htmlFor="bet-target">Target</FieldLabel>
                    <InputGroup>
                        {prefix && (
                            <InputGroupAddon align="inline-start">
                                <InputGroupText>{prefix}</InputGroupText>
                            </InputGroupAddon>
                        )}
                        <InputGroupInput
                            id="bet-target"
                            inputMode="decimal"
                            autoComplete="off"
                            value={form.target ?? ''}
                            aria-invalid={!!fieldErrors.target || undefined}
                            onChange={(event) => change({ target: event.target.value.replace(',', '.') })}
                            onBlur={() => touch('target')}
                            placeholder="Value to reach"
                        />
                        {unit && (
                            <InputGroupAddon align="inline-end">
                                <InputGroupText>{unit}</InputGroupText>
                            </InputGroupAddon>
                        )}
                    </InputGroup>
                    {fieldErrors.target ? (
                        <FieldError>{fieldErrors.target}</FieldError>
                    ) : (
                        changeText && <FieldDescription>{changeText}</FieldDescription>
                    )}
                </Field>
            </div>
            {needsDirection && (
                <Field>
                    <FieldTitle>Should it go up or down?</FieldTitle>
                    <RadioGroup
                        className="flex w-auto flex-wrap gap-x-5 gap-y-2"
                        value={direction}
                        onValueChange={(value: unknown) =>
                            change({ direction: value === 'decrease' ? 'decrease' : 'increase' })
                        }
                        aria-label="Goal direction"
                    >
                        <Label className="Bets__directionOption">
                            <RadioGroupItem value="increase" />
                            Increase
                        </Label>
                        <Label className="Bets__directionOption">
                            <RadioGroupItem value="decrease" />
                            Decrease
                        </Label>
                    </RadioGroup>
                    <FieldDescription>
                        This insight has no value yet, so Bets cannot tell from the target.
                    </FieldDescription>
                </Field>
            )}
        </div>
    )
}
