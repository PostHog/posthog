import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconGraph, IconPencil, IconPlus } from '@posthog/icons'
import {
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    ComboboxTrigger,
} from '@posthog/quill'

import type { BetInsightOption } from '../lib/betForm'
import { betFormLogic } from '../logics/betFormLogic'

export function BetInsightPicker({
    id,
    inputId,
    value,
    options,
    placeholder,
    invalid = false,
    onSelect,
    onClose,
    onDescribe,
    compact = false,
}: {
    id: string
    inputId?: string
    value: string
    options: BetInsightOption[]
    placeholder: string
    invalid?: boolean
    onSelect: (insight: string) => void
    onClose?: () => void
    onDescribe?: () => void
    compact?: boolean
}): JSX.Element {
    const { insightSearch, insightsLoading, insightNames } = useValues(betFormLogic({ id }))
    const { setInsightSearch } = useActions(betFormLogic({ id }))
    const triggerRef = useRef<HTMLButtonElement>(null)
    const inputRef = useRef<HTMLInputElement>(null)
    const [open, setOpen] = useState(false)
    const label = value ? (insightNames[value] ?? value) : ''
    return (
        <Combobox
            items={options.map((option) => option.value)}
            filter={null}
            autoHighlight
            value={value || null}
            onValueChange={(next: string | null) => next && onSelect(next)}
            open={open}
            onOpenChange={(next: boolean) => {
                setOpen(next)
                if (next) {
                    setInsightSearch('')
                    window.requestAnimationFrame(() => inputRef.current?.focus())
                } else {
                    onClose?.()
                }
            }}
            inputValue={insightSearch}
            onInputValueChange={(next: string) => setInsightSearch(next)}
        >
            <span
                className="contents"
                onKeyDownCapture={(event) => {
                    if (event.key.length === 1 && !event.metaKey && !event.ctrlKey && !event.altKey) {
                        event.preventDefault()
                        event.stopPropagation()
                        setInsightSearch((open ? insightSearch : '') + event.key)
                        if (!open) {
                            setOpen(true)
                        }
                        window.requestAnimationFrame(() => inputRef.current?.focus())
                    }
                }}
            >
                <ComboboxTrigger
                    render={
                        <Button
                            ref={triggerRef}
                            id={inputId}
                            variant="outline"
                            left
                            aria-invalid={invalid || undefined}
                            className={compact ? undefined : 'w-full justify-start'}
                        >
                            {compact ? <IconPlus /> : <IconGraph />}
                            <span
                                className={`min-w-0 flex-1 truncate text-start ${label || compact ? '' : 'text-muted-foreground'}`}
                            >
                                {label || (insightsLoading && !compact ? 'Loading insights…' : placeholder)}
                            </span>
                        </Button>
                    }
                />
            </span>
            <ComboboxContent anchor={triggerRef} className="min-w-[320px]">
                <div className="p-1">
                    <ComboboxInput
                        ref={inputRef}
                        placeholder="Search insights"
                        showTrigger={false}
                        className="w-full"
                    />
                </div>
                <ComboboxEmpty>{insightsLoading ? 'Loading insights…' : 'No saved insights match.'}</ComboboxEmpty>
                <ComboboxList>
                    {(item: string) => {
                        const option = options.find((entry) => entry.value === item)
                        return (
                            <ComboboxItem
                                key={item}
                                value={item}
                                disabled={!!option?.disabledReason}
                                description={option?.disabledReason ?? undefined}
                            >
                                <span className="min-w-0 truncate">{option?.label ?? item}</span>
                            </ComboboxItem>
                        )
                    }}
                </ComboboxList>
                {onDescribe && (
                    <div className="border-t border-border p-1">
                        <Button
                            type="button"
                            variant="default"
                            size="sm"
                            left
                            className="w-full"
                            onClick={() => {
                                setOpen(false)
                                onDescribe()
                            }}
                            data-attr="bets-form-describe-goal"
                        >
                            <IconPencil />
                            None fits? Describe how to measure it
                        </Button>
                    </div>
                )}
            </ComboboxContent>
        </Combobox>
    )
}
