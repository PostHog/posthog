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
                        onValueChange={(next: string[], eventDetails) => {
                            // Escape with the list closed would otherwise clear every selection.
                            if (eventDetails.reason === 'escape-key') {
                                eventDetails.allowPropagation()
                                return
                            }
                            if ((next ?? []).length <= limit) {
                                onChange(next ?? [])
                            }
                        }}
                    >
                        <AccountPropertyChips
                            inputId={inputId}
                            placeholder={placeholder}
                            labelsByKey={labelsByKey}
                            loading={loading}
                            disabledReason={disabledReason}
                        />
                    </Combobox>
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
    disabledReason,
}: {
    inputId: string
    placeholder: string
    labelsByKey: Record<string, string>
    loading: boolean
    disabledReason: string | undefined
}): JSX.Element {
    const anchor = useComboboxAnchor()

    return (
        <>
            <ComboboxChips ref={anchor} disabledReason={disabledReason} data-attr="ai-context-account-properties">
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
