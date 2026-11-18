import { Fragment, useRef, useState } from 'react'

import {
    Button,
    Combobox,
    ComboboxChip,
    ComboboxChips,
    ComboboxChipsInput,
    ComboboxContent,
    ComboboxItem,
    ComboboxList,
    ComboboxSeparator,
    ComboboxValue,
    MenuLabel,
    Spinner,
} from '@posthog/quill'

import type { LemonInputSelectOption } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

// An object, not a string, so no channel key can be mistaken for the refresh row.
const REFRESH_ITEM = { refresh: true } as const
type Item = string | typeof REFRESH_ITEM

export interface QuillSlackChannelPickerProps {
    values: string[]
    options: LemonInputSelectOption[]
    multiple: boolean
    disabled?: boolean
    loading: boolean
    invalid: boolean
    refreshDisabledReason?: string | null
    onChange: (values: string[]) => void
    onInputChange: (input: string) => void
    onFocus: () => void
    onBlur: () => void
    onRefresh: () => void
}

export function QuillSlackChannelPicker({
    values,
    options,
    multiple,
    disabled,
    loading,
    invalid,
    refreshDisabledReason,
    onChange,
    onInputChange,
    onFocus,
    onBlur,
    onRefresh,
}: QuillSlackChannelPickerProps): JSX.Element {
    const [inputValue, setInputValue] = useState('')
    const anchor = useRef<HTMLDivElement>(null)

    const optionsByKey = new Map(options.map((option) => [option.key, option]))
    const query = inputValue.trim().toLowerCase()
    const matchingKeys = options
        .filter((option) => !query || option.label.toLowerCase().includes(query))
        .map((option) => option.key)
    const items: Item[] = [...matchingKeys, REFRESH_ITEM]

    const labelFor = (key: string): string => optionsByKey.get(key)?.label ?? key

    const commitValues = (keys: string[]): void => {
        if (multiple) {
            onChange(keys)
            return
        }

        const added = keys.filter((key) => !values.includes(key))
        onChange(added.length ? [added[added.length - 1]] : keys.slice(-1))
    }

    return (
        <Combobox
            multiple
            items={items}
            filter={null}
            disabled={disabled}
            value={values as Item[]}
            itemToStringLabel={(item: Item) => (typeof item === 'string' ? labelFor(item) : '')}
            inputValue={inputValue}
            onInputValueChange={(next: string) => {
                setInputValue(next)
                onInputChange(next)
            }}
            onOpenChange={(open, eventDetails) => {
                if (!open && (eventDetails.reason === 'focus-out' || eventDetails.reason === 'outside-press')) {
                    onBlur()
                }
            }}
            onValueChange={(next: Item[]) => {
                if (next.includes(REFRESH_ITEM)) {
                    onRefresh()
                    return
                }

                commitValues(next.filter((item): item is string => typeof item === 'string'))
            }}
        >
            <ComboboxChips ref={anchor} aria-invalid={invalid || undefined}>
                <ComboboxValue>
                    {(selected: Item[]) => (
                        <>
                            {(selected as string[]).map((key) => (
                                <ComboboxChip key={key} title={labelFor(key)}>
                                    {labelFor(key)}
                                </ComboboxChip>
                            ))}
                            <ComboboxChipsInput
                                placeholder={
                                    selected.length && !multiple
                                        ? undefined
                                        : multiple
                                          ? 'Select channels...'
                                          : 'Select a channel...'
                                }
                                onFocus={onFocus}
                                data-attr="select-slack-channel"
                            />
                        </>
                    )}
                </ComboboxValue>
            </ComboboxChips>
            <ComboboxContent anchor={anchor} className="max-w-120">
                {matchingKeys.length === 0 ? (
                    <MenuLabel className="whitespace-normal">
                        {loading ? (
                            <span className="flex items-center gap-2">
                                <Spinner />
                                Loading channels…
                            </span>
                        ) : (
                            <span>
                                No channels found. Make sure the PostHog Slack App is installed in the channel.{' '}
                                <Button
                                    variant="link"
                                    size="inline"
                                    nativeButton={false}
                                    render={
                                        <LinkPrimitive
                                            to="https://posthog.com/docs/cdp/destinations/slack"
                                            target="_blank"
                                        />
                                    }
                                >
                                    See the docs for more information.
                                </Button>
                            </span>
                        )}
                    </MenuLabel>
                ) : null}
                <ComboboxList>
                    {(item: Item) =>
                        typeof item === 'string' ? (
                            <ComboboxItem key={item} value={item}>
                                {optionsByKey.get(item)?.labelComponent ?? labelFor(item)}
                            </ComboboxItem>
                        ) : (
                            <Fragment key="refresh">
                                {matchingKeys.length > 0 && <ComboboxSeparator />}
                                <ComboboxItem value={item} action disabledReason={refreshDisabledReason}>
                                    Refresh channels
                                </ComboboxItem>
                            </Fragment>
                        )
                    }
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
