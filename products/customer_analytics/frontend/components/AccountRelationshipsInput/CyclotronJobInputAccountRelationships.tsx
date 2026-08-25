import { useActions, useValues } from 'kea'
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
    const { definitions, definitionsLoading, pendingDefinitionIds } = useValues(accountRelationshipsInputLogic)
    const { addPendingDefinition, removePendingDefinition } = useActions(accountRelationshipsInputLogic)

    const assignmentsByDefinitionId: Record<string, RelationshipAssignment> = value ?? {}
    const rows: [string, RelationshipAssignment | undefined][] = [
        ...Object.entries(assignmentsByDefinitionId),
        ...pendingDefinitionIds
            .filter((definitionId) => !(definitionId in assignmentsByDefinitionId))
            .map((definitionId): [string, undefined] => [definitionId, undefined]),
    ]
    const selectedIds = new Set(rows.map(([definitionId]) => definitionId))
    const available = definitions.filter((d) => !selectedIds.has(d.id))

    const setAssignment = (definitionId: string, assignment: RelationshipAssignment): void => {
        removePendingDefinition(definitionId)
        onChange({ ...assignmentsByDefinitionId, [definitionId]: assignment })
    }
    const removeDefinition = (definitionId: string): void => {
        removePendingDefinition(definitionId)
        if (definitionId in assignmentsByDefinitionId) {
            const next = { ...assignmentsByDefinitionId }
            delete next[definitionId]
            onChange(next)
        }
    }

    return (
        <div className="flex flex-col gap-2">
            {rows.map(([definitionId, assignment]) => {
                const definition = definitions.find((d) => d.id === definitionId)
                const isPending = assignment === undefined
                return (
                    <div className="flex gap-2 items-center" key={definitionId}>
                        <div className="flex-1 min-w-50 font-medium truncate" title={definition?.name ?? definitionId}>
                            {definition?.name ?? <span className="text-secondary italic">Unknown relationship</span>}
                        </div>
                        <MemberSelect
                            value={assignment?.id ?? null}
                            allowNone
                            defaultLabel="Clear assignment"
                            onChange={(user) =>
                                setAssignment(definitionId, user ? { type: 'user', id: user.id } : null)
                            }
                        >
                            {(selectedUser) => (
                                <LemonButton size="small" type="secondary">
                                    {selectedUser ? (
                                        fullName(selectedUser)
                                    ) : isPending ? (
                                        <span className="text-secondary">Select member</span>
                                    ) : (
                                        'Clear assignment'
                                    )}
                                </LemonButton>
                            )}
                        </MemberSelect>
                        <LemonButton icon={<IconX />} size="small" onClick={() => removeDefinition(definitionId)} />
                    </div>
                )
            })}
            <AddDefinitionDropdown available={available} onSelect={addPendingDefinition} loading={definitionsLoading} />
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
