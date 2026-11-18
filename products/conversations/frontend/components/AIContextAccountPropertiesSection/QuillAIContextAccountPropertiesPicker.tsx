import { useId } from 'react'

import {
    Card,
    CardContent,
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
    FieldDescription,
    Skeleton,
    useComboboxAnchor,
} from '@posthog/quill'

export function QuillAIContextAccountPropertiesPicker({
    options,
    loading,
    value,
    limit,
    placeholder,
    disabledReason,
    onChange,
}: {
    options: { key: string; label: string }[]
    loading: boolean
    value: string[]
    limit: number
    placeholder: string
    disabledReason: string | undefined
    onChange: (value: string[]) => void
}): JSX.Element {
    const inputId = useId()
    const labelsByKey = Object.fromEntries(options.map((option) => [option.key, option.label]))

    return (
        <Card size="sm" className="max-w-200">
            <CardContent>
                <Field>
                    <Combobox<string, true>
                        multiple
                        autoHighlight
                        items={options.map((option) => option.key)}
                        itemToStringLabel={(key: string) => labelsByKey[key] ?? key}
                        value={value}
                        onValueChange={(next: string[]) => {
                            if ((next ?? []).length <= limit) {
                                onChange(next ?? [])
                            }
                        }}
                        disabled={!!disabledReason}
                    >
                        <AccountPropertyChips
                            inputId={inputId}
                            placeholder={placeholder}
                            labelsByKey={labelsByKey}
                            loading={loading}
                            disabled={!!disabledReason}
                        />
                    </Combobox>
                    {/* An input has no disabledReason, so the reason sits under it instead of in a tooltip. */}
                    {disabledReason && <FieldDescription>{disabledReason}</FieldDescription>}
                </Field>
            </CardContent>
        </Card>
    )
}

function AccountPropertyChips({
    inputId,
    placeholder,
    labelsByKey,
    loading,
    disabled,
}: {
    inputId: string
    placeholder: string
    labelsByKey: Record<string, string>
    loading: boolean
    disabled: boolean
}): JSX.Element {
    const anchor = useComboboxAnchor()

    return (
        <>
            <ComboboxChips ref={anchor} data-attr="ai-context-account-properties">
                <ComboboxValue>
                    {(values: string[]) => (
                        <>
                            {values.map((key) => (
                                <ComboboxChip key={key} title={labelsByKey[key] ?? key}>
                                    {labelsByKey[key] ?? key}
                                </ComboboxChip>
                            ))}
                            <ComboboxChipsInput
                                id={inputId}
                                aria-label={placeholder}
                                placeholder={values.length ? '' : placeholder}
                                disabled={disabled}
                            />
                        </>
                    )}
                </ComboboxValue>
            </ComboboxChips>
            <ComboboxContent anchor={anchor}>
                <ComboboxEmpty>
                    {loading ? (
                        <div className="flex w-56 flex-col gap-2">
                            <Skeleton className="h-3 w-3/4" />
                            <Skeleton className="h-3 w-1/2" />
                        </div>
                    ) : (
                        'No account properties yet. Add them in Customer analytics first.'
                    )}
                </ComboboxEmpty>
                <ComboboxList>
                    {(key: string) => (
                        <ComboboxItem key={key} value={key}>
                            {labelsByKey[key] ?? key}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </>
    )
}
