import { useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconPlus, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'
import { MemberSelect } from 'lib/components/MemberSelect'
import { Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from 'lib/ui/quill'

import type { AccountRelationshipDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountRelationshipsInputLogic } from './accountRelationshipsInputLogic'

type RelationshipAssignment = { type: 'user'; id: number } | null

export default function CyclotronJobInputAccountRelationships({
    value,
    onChange,
}: CustomInputRendererProps): JSX.Element {
    const { definitions, definitionsLoading } = useValues(accountRelationshipsInputLogic)

    // Keys are definition UUIDs (stable across renames); values are user assignments or null (ends assignment)
    const assignments: Record<string, RelationshipAssignment> = value ?? {}
    const entries = Object.entries(assignments)
    const selectedIds = new Set(entries.map(([id]) => id))
    const available = definitions.filter((d) => !selectedIds.has(d.id))

    const setAssignment = (id: string, assignment: RelationshipAssignment): void =>
        onChange({ ...assignments, [id]: assignment })
    const addDefinition = (id: string): void => onChange({ ...assignments, [id]: null })
    const removeDefinition = (id: string): void => {
        const next = { ...assignments }
        delete next[id]
        onChange(next)
    }

    return (
        <div className="flex flex-col gap-2">
            {entries.map(([id, assignment]) => {
                const definition = definitions.find((d) => d.id === id)
                return (
                    <div className="flex gap-2 items-center" key={id}>
                        <div className="flex-1 min-w-50 font-medium truncate" title={definition?.name ?? id}>
                            {definition?.name ?? <span className="text-secondary italic">Unknown relationship</span>}
                        </div>
                        <MemberSelect
                            value={assignment?.id ?? null}
                            allowNone
                            defaultLabel="Clear assignment"
                            onChange={(user) => setAssignment(id, user ? { type: 'user', id: user.id } : null)}
                        />
                        <LemonButton icon={<IconX />} size="small" onClick={() => removeDefinition(id)} />
                    </div>
                )
            })}
            <AddDefinitionDropdown available={available} onSelect={addDefinition} loading={definitionsLoading} />
        </div>
    )
}

function AddDefinitionDropdown({
    available,
    onSelect,
    loading,
}: {
    available: AccountRelationshipDefinitionApi[]
    onSelect: (id: string) => void
    loading: boolean
}): JSX.Element {
    const [open, setOpen] = useState(false)
    const triggerRef = useRef<HTMLButtonElement>(null)

    return (
        <Combobox
            items={available}
            itemToStringValue={(d: AccountRelationshipDefinitionApi) => d.name}
            open={open}
            onOpenChange={setOpen}
            value={null}
            onValueChange={(d: AccountRelationshipDefinitionApi | null) => {
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
                disabledReason={loading ? 'Loading relationship definitions…' : undefined}
                onClick={() => setOpen(true)}
            >
                Add relationship
            </LemonButton>
            <ComboboxContent anchor={triggerRef}>
                <ComboboxInput placeholder="Search relationships" showTrigger={false} />
                <ComboboxEmpty>No relationships found</ComboboxEmpty>
                <ComboboxList>
                    {(d: AccountRelationshipDefinitionApi) => (
                        <ComboboxItem key={d.id} value={d}>
                            {d.name}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
