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
    useComboboxAnchor,
} from '@posthog/quill'

// Large workspaces have thousands of channels, so the list shows the top matches only.
const MAX_CHANNEL_RESULTS = 100

import { SlackChannelOption } from '../../scenes/settings/slackSettingsHelpers'

export function QuillSlackChannelMultiSelect({
    id,
    options,
    value,
    placeholder,
    onChange,
}: {
    id: string
    options: SlackChannelOption[]
    value: string[]
    placeholder: string
    onChange: (value: string[]) => void
}): JSX.Element {
    const labelsByKey = Object.fromEntries(options.map((option) => [option.key, option.label]))

    return (
        <Combobox<string, true>
            multiple
            autoHighlight
            items={options.map((option) => option.key)}
            limit={MAX_CHANNEL_RESULTS}
            itemToStringLabel={(key: string) => labelsByKey[key] ?? key}
            value={value}
            onValueChange={(next: string[], eventDetails) => {
                // Escape with the list closed would otherwise clear every selection.
                if (eventDetails.reason === 'escape-key') {
                    eventDetails.allowPropagation()
                    return
                }
                onChange(next ?? [])
            }}
        >
            <ChannelChips id={id} placeholder={placeholder} labelsByKey={labelsByKey} />
        </Combobox>
    )
}

function ChannelChips({
    id,
    placeholder,
    labelsByKey,
}: {
    id: string
    placeholder: string
    labelsByKey: Record<string, string>
}): JSX.Element {
    const anchor = useComboboxAnchor()

    return (
        <>
            <ComboboxChips ref={anchor}>
                <ComboboxValue>
                    {(values: string[]) => (
                        <>
                            {values.map((key) => (
                                <ComboboxChip key={key}>{labelsByKey[key] ?? key}</ComboboxChip>
                            ))}
                            <ComboboxChipsInput id={id} placeholder={values.length ? '' : placeholder} />
                        </>
                    )}
                </ComboboxValue>
            </ComboboxChips>
            <ComboboxContent anchor={anchor}>
                <ComboboxEmpty>No matching channels</ComboboxEmpty>
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
