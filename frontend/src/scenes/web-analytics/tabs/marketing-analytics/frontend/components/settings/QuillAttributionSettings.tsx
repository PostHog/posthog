import { useId } from 'react'

import { IconInfo } from '@posthog/icons'
import {
    Button,
    Field,
    FieldDescription,
    FieldError,
    FieldLabel,
    Heading,
    Input,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Spinner,
    Text,
    ToggleGroup,
    ToggleGroupItem,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { AttributionMode } from '~/queries/schema/schema-general'

import { ATTRIBUTION_WINDOW_OPTIONS, MAX_ATTRIBUTION_WINDOW_DAYS, MIN_ATTRIBUTION_WINDOW_DAYS } from '../../logic/utils'

type WindowValue = number | string

function LabelHelp({ label, help }: { label: string; help: string }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger delay={0} render={<Button size="icon-xs" aria-label={`About ${label.toLowerCase()}`} />}>
                <IconInfo />
            </TooltipTrigger>
            <TooltipContent className="max-w-80">{help}</TooltipContent>
        </Tooltip>
    )
}

export function QuillAttributionSettings({
    currentTeamLoading,
    windowSelectValue,
    onDaysChange,
    localDays,
    onCustomInputChange,
    onKeyDown,
    hasError,
    onSave,
    saveDisabledReason,
    restrictedReason,
    attributionModeOptions,
    localAttributionMode,
    onAttributionModeChange,
    attributionModeDescription,
}: {
    currentTeamLoading: boolean
    windowSelectValue: WindowValue
    onDaysChange: (days: WindowValue) => void
    localDays: number
    onCustomInputChange: (value: number | undefined) => void
    onKeyDown: (e: React.KeyboardEvent) => void
    hasError: boolean
    onSave: () => void
    saveDisabledReason: string | null
    restrictedReason: string | null
    attributionModeOptions: { value: AttributionMode; label: string }[]
    localAttributionMode: AttributionMode
    onAttributionModeChange: (mode: AttributionMode) => void
    attributionModeDescription: string
}): JSX.Element {
    const windowInputId = useId()

    return (
        <section className="flex flex-col gap-4">
            <div className="flex flex-col gap-1">
                <Heading size="sm" render={<h3 className="m-0 flex items-center gap-2" />}>
                    Attribution Settings
                    {currentTeamLoading && <Spinner />}
                </Heading>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Configure how conversions are attributed to marketing campaigns.
                </Text>
            </div>

            <Field data-invalid={hasError || undefined}>
                <div className="flex items-center gap-1">
                    <FieldLabel htmlFor={windowInputId}>Attribution Window</FieldLabel>
                    <LabelHelp
                        label="Attribution Window"
                        help="The attribution window determines how far back in time to look for marketing touchpoints when attributing conversions. Example: With a 30-day window, if someone converts today, we'll look back 30 days for any UTM campaigns they interacted with. Recommendation: Use 30-60 days for short sales cycles, 90+ days for longer consideration periods."
                    />
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <Select<WindowValue>
                        value={windowSelectValue}
                        onValueChange={(next) => next !== null && onDaysChange(next)}
                    >
                        <SelectTrigger
                            aria-label="Attribution window"
                            className="w-50"
                            data-attr="attribution-window-select"
                            disabledReason={restrictedReason}
                        >
                            <SelectValue>
                                {(selected: WindowValue | null) =>
                                    ATTRIBUTION_WINDOW_OPTIONS.find((option) => option.value === selected)?.label
                                }
                            </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                            {ATTRIBUTION_WINDOW_OPTIONS.map((option) => (
                                <SelectItem key={option.value} value={option.value}>
                                    {option.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                    <Input
                        id={windowInputId}
                        type="number"
                        className="w-32"
                        value={localDays}
                        onChange={(event) =>
                            onCustomInputChange(event.target.value === '' ? undefined : Number(event.target.value))
                        }
                        onKeyDown={onKeyDown}
                        placeholder={`${MIN_ATTRIBUTION_WINDOW_DAYS}-${MAX_ATTRIBUTION_WINDOW_DAYS}`}
                        min={MIN_ATTRIBUTION_WINDOW_DAYS}
                        max={MAX_ATTRIBUTION_WINDOW_DAYS}
                        aria-invalid={hasError || undefined}
                        data-attr="attribution-window-custom-input"
                        disabledReason={restrictedReason}
                    />
                    <Button
                        variant="primary"
                        onClick={onSave}
                        disabledReason={saveDisabledReason}
                        data-attr="attribution-window-save-button"
                    >
                        Save
                    </Button>
                </div>
                {hasError ? (
                    <FieldError>{`Please enter a value between ${MIN_ATTRIBUTION_WINDOW_DAYS} and ${MAX_ATTRIBUTION_WINDOW_DAYS} days`}</FieldError>
                ) : (
                    <FieldDescription>
                        How far back to look for marketing touchpoints when attributing conversions
                    </FieldDescription>
                )}
            </Field>

            <Field>
                <div className="flex items-center gap-1">
                    <Text size="xs" weight="medium" render={<span />}>
                        Attribution Mode
                    </Text>
                    <LabelHelp
                        label="Attribution Mode"
                        help="Attribution mode determines how credit for a conversion is distributed across marketing touchpoints. First touch: 100% credit to the first touchpoint. Last touch: 100% credit to the last touchpoint. Linear: Equal credit across all touchpoints. Time decay: More credit to recent touchpoints, with credit halving at regular intervals. Position based: 40% first, 40% last, 20% distributed among middle touchpoints."
                    />
                </div>
                <ToggleGroup
                    variant="outline"
                    aria-label="Attribution mode"
                    className="flex-wrap"
                    value={[localAttributionMode]}
                    onValueChange={(next: string[]) => {
                        const picked = next[0] as AttributionMode | undefined
                        if (picked) {
                            onAttributionModeChange(picked)
                        }
                    }}
                >
                    {attributionModeOptions.map((option) => (
                        <ToggleGroupItem
                            key={option.value}
                            value={option.value}
                            data-attr={`attribution-mode-${option.value.toLowerCase().replace('_', '-')}`}
                            disabledReason={restrictedReason}
                        >
                            {option.label}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
                <FieldDescription>{attributionModeDescription}</FieldDescription>
            </Field>
        </section>
    )
}
