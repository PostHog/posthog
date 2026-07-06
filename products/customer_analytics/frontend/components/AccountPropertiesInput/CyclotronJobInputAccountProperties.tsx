import { useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconPlus, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import { Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from 'lib/ui/quill'

import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountPropertiesInputLogic } from './accountPropertiesInputLogic'

export default function CyclotronJobInputAccountProperties({
    value,
    onChange,
    sampleGlobalsWithInputs,
}: CustomInputRendererProps): JSX.Element {
    const { definitions, nameById, definitionsLoading } = useValues(accountPropertiesInputLogic)

    // Keys are custom property definition ids (stable across renames); values are Hog expressions.
    const properties: Record<string, string> = value ?? {}
    const entries = Object.entries(properties)
    const selectedIds = new Set(entries.map(([id]) => id))
    const available = definitions.filter((d) => !selectedIds.has(d.id))

    const setProperty = (id: string, hogValue: string): void => onChange({ ...properties, [id]: hogValue })
    const addProperty = (id: string): void => onChange({ ...properties, [id]: '' })
    const removeProperty = (id: string): void => {
        const next = { ...properties }
        delete next[id]
        onChange(next)
    }

    return (
        <div className="flex flex-col gap-2">
            {entries.map(([id, hogValue]) => {
                const label = nameById[id]
                return (
                    <div className="flex gap-2 items-center" key={id}>
                        <div className="flex-1 min-w-50 font-medium truncate" title={label ?? id}>
                            {label ?? <span className="text-secondary italic">Unknown property</span>}
                        </div>
                        <CodeEditorInline
                            className="overflow-hidden flex-2"
                            minHeight="37"
                            value={hogValue}
                            onChange={(val) => setProperty(id, val ?? '')}
                            language="hogTemplate"
                            globals={sampleGlobalsWithInputs ?? undefined}
                        />
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
