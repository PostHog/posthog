import { useId } from 'react'

import { IconInfo } from '@posthog/icons'
import {
    Badge,
    Button,
    Combobox,
    ComboboxChip,
    ComboboxChips,
    ComboboxChipsInput,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxItem,
    ComboboxList,
    ComboboxValue,
    Field,
    FieldContent,
    FieldDescription,
    FieldGroup,
    FieldLabel,
    Item,
    ItemContent,
    ItemDescription,
    Label,
    RadioGroup,
    RadioGroupItem,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    useComboboxAnchor,
} from '@posthog/quill'

import { DataWarehouseSavedQueryIncrementalCheck } from '~/types'

import {
    INCREMENTAL_CHECK_LOADING,
    INCREMENTAL_KEY_HELP,
    INCREMENTAL_KEY_LABEL,
    IncrementalConfigDraft,
    LOOKBACK_HELP,
    LOOKBACK_OPTIONS,
    REFRESH_MODE_OPTIONS,
    RefreshMode,
    UNIQUE_KEY_HELP,
    UNIQUE_KEY_LABEL,
    uniqueKeyCandidates,
} from './IncrementalConfigFields'

const LOOKBACK_LABEL = 'Lookback window'

function LabelWithHelp({ htmlFor, label, help }: { htmlFor: string; label: string; help: string }): JSX.Element {
    return (
        <FieldLabel htmlFor={htmlFor} className="flex items-center gap-1">
            {label}
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={<Button size="icon-xs" aria-label={`About ${label.toLowerCase()}`} />}
                >
                    <IconInfo />
                </TooltipTrigger>
                <TooltipContent className="max-w-80">{help}</TooltipContent>
            </Tooltip>
        </FieldLabel>
    )
}

function UniqueKeyChips({ id, check }: { id: string; check: DataWarehouseSavedQueryIncrementalCheck }): JSX.Element {
    const anchor = useComboboxAnchor()
    return (
        <>
            <ComboboxChips ref={anchor} data-attr="materialization-incremental-unique-key">
                <ComboboxValue>
                    {(values: string[]) => (
                        <>
                            {values.map((column) => (
                                <ComboboxChip key={column}>{column}</ComboboxChip>
                            ))}
                            <ComboboxChipsInput id={id} placeholder={values.length ? '' : 'Add column'} />
                        </>
                    )}
                </ComboboxValue>
            </ComboboxChips>
            <ComboboxContent anchor={anchor}>
                <ComboboxEmpty>No matching columns</ComboboxEmpty>
                <ComboboxList>
                    {(column: string) => (
                        <ComboboxItem key={column} value={column} description={check.key_candidate_types?.[column]}>
                            {column}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </>
    )
}

function UniqueKeyCombobox({
    id,
    check,
    value,
    onChange,
}: {
    id: string
    check: DataWarehouseSavedQueryIncrementalCheck
    value: string[]
    onChange: (value: string[]) => void
}): JSX.Element {
    return (
        <Combobox<string, true>
            multiple
            items={uniqueKeyCandidates(check)}
            value={value}
            onValueChange={(next) => onChange(next ?? [])}
        >
            <UniqueKeyChips id={id} check={check} />
        </Combobox>
    )
}

export interface QuillIncrementalConfigOptionsProps {
    check: DataWarehouseSavedQueryIncrementalCheck | null
    draft: IncrementalConfigDraft
    onChange: (draft: Partial<IncrementalConfigDraft>) => void
}

export function QuillIncrementalConfigOptions({
    check,
    draft,
    onChange,
}: QuillIncrementalConfigOptionsProps): JSX.Element | null {
    const id = useId()

    if (check === INCREMENTAL_CHECK_LOADING) {
        return (
            <div className="flex flex-col gap-2" data-attr="materialization-refresh-mode-loading">
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-full" />
            </div>
        )
    }

    if (!check) {
        return null
    }

    if (!check.eligible || check.key_candidates.length === 0) {
        return (
            <Item variant="outline" size="sm" tone="info">
                <ItemContent>
                    <ItemDescription>
                        This query is always refreshed in full.{' '}
                        {check.blockers[0] ?? 'It has no column that can track which rows are new.'}
                    </ItemDescription>
                </ItemContent>
            </Item>
        )
    }

    return (
        <FieldGroup>
            <RadioGroup
                value={draft.enabled ? 'incremental' : 'full_refresh'}
                onValueChange={(mode) => onChange({ enabled: (mode as RefreshMode) === 'incremental' })}
            >
                {REFRESH_MODE_OPTIONS.map((option) => (
                    <Field key={option.value} orientation="horizontal" className="items-start">
                        <RadioGroupItem
                            value={option.value}
                            id={`${id}-${option.value}`}
                            data-attr={`materialization-refresh-mode-${option.value}`}
                        />
                        <FieldContent>
                            <Label htmlFor={`${id}-${option.value}`}>{option.label}</Label>
                            <FieldDescription>{option.description}</FieldDescription>
                        </FieldContent>
                    </Field>
                ))}
            </RadioGroup>
            {draft.enabled && (
                <FieldGroup className="max-w-120 pl-6">
                    <Field>
                        <LabelWithHelp
                            htmlFor={`${id}-key`}
                            label={INCREMENTAL_KEY_LABEL}
                            help={INCREMENTAL_KEY_HELP}
                        />
                        <Select
                            value={draft.incrementalKey}
                            onValueChange={(incrementalKey) => onChange({ incrementalKey: incrementalKey as string })}
                        >
                            <SelectTrigger id={`${id}-key`} data-attr="materialization-incremental-key">
                                <SelectValue placeholder="Select a column" />
                            </SelectTrigger>
                            <SelectContent>
                                {check.key_candidates.map((column) => (
                                    <SelectItem key={column} value={column}>
                                        <span className="flex items-center gap-2">
                                            {column}
                                            {check.key_candidate_types?.[column] && (
                                                <Badge>{check.key_candidate_types[column]}</Badge>
                                            )}
                                        </span>
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </Field>
                    <Field>
                        <LabelWithHelp htmlFor={`${id}-unique`} label={UNIQUE_KEY_LABEL} help={UNIQUE_KEY_HELP} />
                        <UniqueKeyCombobox
                            id={`${id}-unique`}
                            check={check}
                            value={draft.uniqueKey}
                            onChange={(uniqueKey) => onChange({ uniqueKey })}
                        />
                    </Field>
                    <Field>
                        <LabelWithHelp htmlFor={`${id}-lookback`} label={LOOKBACK_LABEL} help={LOOKBACK_HELP} />
                        <Select
                            value={draft.lookbackSeconds}
                            onValueChange={(lookbackSeconds) =>
                                onChange({ lookbackSeconds: lookbackSeconds as number })
                            }
                        >
                            <SelectTrigger id={`${id}-lookback`}>
                                <SelectValue>
                                    {(seconds: number) =>
                                        LOOKBACK_OPTIONS.find((option) => option.value === seconds)?.label
                                    }
                                </SelectValue>
                            </SelectTrigger>
                            <SelectContent>
                                {LOOKBACK_OPTIONS.map((option) => (
                                    <SelectItem key={option.value} value={option.value}>
                                        {option.label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </Field>
                    {check.warnings.length > 0 && (
                        <Item variant="outline" size="sm" tone="warning">
                            <ItemContent>
                                <ul className="m-0 flex flex-col gap-1 pl-4 text-xs">
                                    {check.warnings.map((warning) => (
                                        <li key={warning}>{warning}</li>
                                    ))}
                                </ul>
                            </ItemContent>
                        </Item>
                    )}
                </FieldGroup>
            )}
        </FieldGroup>
    )
}
