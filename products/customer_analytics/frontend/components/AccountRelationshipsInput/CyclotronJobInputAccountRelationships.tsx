import { useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconPlus, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'
import { MemberSelect } from 'lib/components/MemberSelect'
import { Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from 'lib/ui/quill'
import { fullName } from 'lib/utils/strings'

import type { AccountRelationshipDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountRelationshipsInputLogic } from './accountRelationshipsInputLogic'

type RelationshipAssignment = { type: 'user'; id: number } | null

export default function CyclotronJobInputAccountRelationships({
    value,
    onChange,
}: CustomInputRendererProps): JSX.Element {
    const { definitions, definitionsLoading } = useValues(accountRelationshipsInputLogic)

    // Keys are definition UUIDs (stable across renames); values are user assignments or null (ends assignment).
    // Newly added rows stay out of the saved value until the user picks something — writing null on add
    // would silently end the account's active assignment on the next run.
    const assignments: Record<string, RelationshipAssignment> = value ?? {}
    const [pendingIds, setPendingIds] = useState<string[]>([])
    const entries: [string, RelationshipAssignment | undefined][] = [
        ...Object.entries(assignments),
        ...pendingIds.filter((id) => !(id in assignments)).map((id): [string, undefined] => [id, undefined]),
    ]
    const selectedIds = new Set(entries.map(([id]) => id))
    const available = definitions.filter((d) => !selectedIds.has(d.id))

    const setAssignment = (id: string, assignment: RelationshipAssignment): void => {
        setPendingIds((ids) => ids.filter((pending) => pending !== id))
        onChange({ ...assignments, [id]: assignment })
    }
    const addDefinition = (id: string): void => setPendingIds((ids) => [...ids, id])
    const removeDefinition = (id: string): void => {
        setPendingIds((ids) => ids.filter((pending) => pending !== id))
        if (id in assignments) {
            const next = { ...assignments }
            delete next[id]
            onChange(next)
        }
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
                        >
                            {(selectedUser) => (
                                <LemonButton size="small" type="secondary">
                                    {selectedUser ? (
                                        fullName(selectedUser)
                                    ) : assignment === undefined ? (
                                        <span className="text-secondary">Select member</span>
                                    ) : (
                                        'Clear assignment'
                                    )}
                                </LemonButton>
                            )}
                        </MemberSelect>
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
