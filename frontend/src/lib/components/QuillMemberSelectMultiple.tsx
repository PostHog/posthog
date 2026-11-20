import {
    Combobox,
    ComboboxChip,
    ComboboxChips,
    ComboboxChipsInput,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxItem,
    ComboboxList,
    ComboboxValue,
    Spinner,
    useComboboxAnchor,
} from '@posthog/quill'

// Large organizations have thousands of members, so the list shows the top matches only.
const MAX_MEMBER_RESULTS = 100

export function QuillMemberSelectMultiple({
    options,
    value,
    loading,
    onChange,
}: {
    options: { key: string; label: string }[]
    value: string[]
    loading: boolean
    onChange: (keys: string[]) => void
}): JSX.Element {
    const labelsByKey = Object.fromEntries(options.map((option) => [option.key, option.label]))

    return (
        <Combobox<string, true>
            multiple
            autoHighlight
            items={options.map((option) => option.key)}
            limit={MAX_MEMBER_RESULTS}
            itemToStringLabel={(key: string) => labelsByKey[key] ?? key}
            value={value}
            onValueChange={(next: string[]) => onChange(next ?? [])}
        >
            <QuillMemberChips labelsByKey={labelsByKey} loading={loading} />
        </Combobox>
    )
}

function QuillMemberChips({
    labelsByKey,
    loading,
}: {
    labelsByKey: Record<string, string>
    loading: boolean
}): JSX.Element {
    const anchor = useComboboxAnchor()

    return (
        <>
            <ComboboxChips ref={anchor}>
                <ComboboxValue>
                    {(values: string[]) => (
                        <>
                            {values.map((key) => (
                                <ComboboxChip key={key} title={labelsByKey[key] ?? key}>
                                    <span className="ph-no-capture">{labelsByKey[key] ?? key}</span>
                                </ComboboxChip>
                            ))}
                            <ComboboxChipsInput
                                placeholder={values.length ? '' : 'Search for team members to add…'}
                                data-attr="subscribed-users"
                            />
                        </>
                    )}
                </ComboboxValue>
            </ComboboxChips>
            <ComboboxContent anchor={anchor}>
                <ComboboxEmpty>
                    {loading ? (
                        <span className="flex items-center gap-2">
                            <Spinner />
                            Loading...
                        </span>
                    ) : (
                        'No matches'
                    )}
                </ComboboxEmpty>
                <ComboboxList>
                    {(key: string) => (
                        <ComboboxItem key={key} value={key}>
                            <span className="ph-no-capture">{labelsByKey[key] ?? key}</span>
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </>
    )
}
