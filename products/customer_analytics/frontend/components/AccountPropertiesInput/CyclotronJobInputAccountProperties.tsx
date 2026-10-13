import { useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonColorGlyph, LemonSelect } from '@posthog/lemon-ui'

import type { DataColorToken } from 'lib/colors'
import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import { Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from 'lib/ui/quill'

import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountPropertiesInputLogic } from './accountPropertiesInputLogic'

type ClearPropertyMarker = { __posthog_clear_property: true }
type AccountProperties = Record<string, string | ClearPropertyMarker>

function isClearPropertyMarker(value: unknown): value is ClearPropertyMarker {
    return (
        value !== null && typeof value === 'object' && (value as ClearPropertyMarker).__posthog_clear_property === true
    )
}

export default function CyclotronJobInputAccountProperties({
    value,
    onChange,
    sampleGlobalsWithInputs,
}: CustomInputRendererProps): JSX.Element {
    const { definitions, definitionsLoading } = useValues(accountPropertiesInputLogic)

    // Keys stay stable across property renames. The marker distinguishes a user-selected clear
    // from a template that resolves to null.
    // Select properties store the chosen option label as a literal.
    const properties: AccountProperties = value ?? {}
    const entries = Object.entries(properties)
    const selectedIds = new Set(entries.map(([id]) => id))
    const available = definitions.filter((d) => !selectedIds.has(d.id))

    const setProperty = (id: string, hogValue: string): void => onChange({ ...properties, [id]: hogValue })
    const clearProperty = (id: string): void => onChange({ ...properties, [id]: { __posthog_clear_property: true } })
    const addProperty = (id: string): void => onChange({ ...properties, [id]: '' })
    const removeProperty = (id: string): void => {
        const next = { ...properties }
        delete next[id]
        onChange(next)
    }

    return (
        <div className="flex flex-col gap-2">
            {entries.map(([id, hogValue]) => {
                const definition = definitions.find((d) => d.id === id)
                return (
                    <div className="flex flex-wrap gap-2 items-center" key={id}>
                        <div className="flex-1 min-w-50 font-medium truncate" title={definition?.name ?? id}>
                            {definition?.name ?? <span className="text-secondary italic">Unknown property</span>}
                        </div>
                        {isClearPropertyMarker(hogValue) ? (
                            <LemonButton
                                type="secondary"
                                size="small"
                                data-attr="account-properties-set-value"
                                onClick={() => setProperty(id, '')}
                            >
                                Set value
                            </LemonButton>
                        ) : definition?.display_type === 'select' ? (
                            <LemonSelect
                                className="flex-2"
                                value={hogValue || null}
                                onChange={(option) => setProperty(id, option ?? '')}
                                options={(definition.options ?? []).map((option) => ({
                                    value: option.label,
                                    label: (
                                        <span className="inline-flex items-center gap-1.5">
                                            <LemonColorGlyph colorToken={option.color as DataColorToken} size="small" />
                                            {option.label}
                                        </span>
                                    ),
                                }))}
                                placeholder="Select an option"
                            />
                        ) : (
                            <CodeEditorInline
                                className="overflow-hidden flex-2"
                                minHeight="37"
                                value={hogValue}
                                onChange={(val) => setProperty(id, val ?? '')}
                                language="hogTemplate"
                                globals={sampleGlobalsWithInputs ?? undefined}
                            />
                        )}
                        {!isClearPropertyMarker(hogValue) && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                data-attr="account-properties-clear-property"
                                onClick={() => clearProperty(id)}
                            >
                                Clear property
                            </LemonButton>
                        )}
                        <LemonButton icon={<IconX />} size="small" onClick={() => removeProperty(id)} />
                    </div>
                )
            })}
            <AddPropertyDropdown available={available} onSelect={addProperty} loading={definitionsLoading} />
        </div>
    )
}

function AddPropertyDropdown({
    available,
    onSelect,
    loading,
}: {
    available: CustomPropertyDefinitionApi[]
    onSelect: (id: string) => void
    loading: boolean
}): JSX.Element {
    const [open, setOpen] = useState(false)
    const triggerRef = useRef<HTMLButtonElement>(null)

    return (
        <Combobox
            items={available}
            itemToStringValue={(d: CustomPropertyDefinitionApi) => d.name}
            open={open}
            onOpenChange={setOpen}
            value={null}
            onValueChange={(d: CustomPropertyDefinitionApi | null) => {
                if (d) {
                    onSelect(d.id)
                }
                setOpen(false)
            }}
        >
            <LemonButton
                ref={triggerRef}
                type="secondary"
                size="small"
                icon={<IconPlus />}
                loading={loading}
                disabledReason={loading ? 'Loading properties…' : undefined}
                onClick={() => setOpen(true)}
            >
                Add property
            </LemonButton>
            <ComboboxContent anchor={triggerRef}>
                <ComboboxInput placeholder="Search properties" showTrigger={false} />
                <ComboboxEmpty>No properties found</ComboboxEmpty>
                <ComboboxList>
                    {(d: CustomPropertyDefinitionApi) => (
                        <ComboboxItem key={d.id} value={d}>
                            {d.name}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
