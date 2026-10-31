import { useActions, useValues } from 'kea'

import { IconChevronDown, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { hierarchyFieldKey } from './biHierarchies'
import { biHierarchyLogic } from './biHierarchyLogic'

export function BIHierarchyModal({ tabId }: { tabId: string }): JSX.Element | null {
    const { draft, availableFields, draftError } = useValues(biHierarchyLogic({ tabId }))
    const { setDraft, saveHierarchy, moveLevel, removeLevel, addLevel } = useActions(biHierarchyLogic({ tabId }))
    if (!draft) {
        return null
    }
    return (
        <LemonModal
            isOpen
            title="Named hierarchy"
            onClose={() => setDraft(null)}
            width={560}
            footer={
                <LemonButton type="primary" onClick={saveHierarchy} disabledReason={draftError}>
                    Save hierarchy
                </LemonButton>
            }
        >
            <div className="flex flex-col gap-3">
                <p className="m-0 text-secondary">
                    Order dimensions from broadest to most detailed. Save the worksheet to reuse this hierarchy in other
                    worksheets.
                </p>
                <LemonField.Pure label="Name">
                    <LemonInput
                        aria-label="Hierarchy name"
                        value={draft.name}
                        onChange={(name) => setDraft({ ...draft, name })}
                        placeholder="For example, Geography"
                    />
                </LemonField.Pure>
                <ol className="m-0 pl-5 space-y-2">
                    {draft.levels.map((field, index) => (
                        <li key={hierarchyFieldKey(field)}>
                            <div className="flex min-w-0 items-center gap-1">
                                <span className="min-w-0 flex-1 truncate" title={field.name}>
                                    {field.name}
                                </span>
                                <LemonButton
                                    icon={<IconChevronDown className="rotate-180" />}
                                    size="xsmall"
                                    aria-label={`Move ${field.name} up`}
                                    disabledReason={index === 0 ? 'Already the first level' : undefined}
                                    onClick={() => moveLevel(index, -1)}
                                />
                                <LemonButton
                                    icon={<IconChevronDown />}
                                    size="xsmall"
                                    aria-label={`Move ${field.name} down`}
                                    disabledReason={
                                        index === draft.levels.length - 1 ? 'Already the last level' : undefined
                                    }
                                    onClick={() => moveLevel(index, 1)}
                                />
                                <LemonButton
                                    icon={<IconTrash />}
                                    size="xsmall"
                                    aria-label={`Remove ${field.name} level`}
                                    onClick={() => removeLevel(index)}
                                />
                            </div>
                        </li>
                    ))}
                </ol>
                <LemonSelect
                    aria-label="Add hierarchy level"
                    placeholder="Add a level"
                    value={null}
                    disabledReason={draft.levels.length >= 10 ? 'A hierarchy can have up to 10 levels' : undefined}
                    options={availableFields.map((field) => ({ value: field.id, label: field.name }))}
                    onChange={(id) => {
                        if (id) {
                            addLevel(id)
                        }
                    }}
                    fullWidth
                />
                <p className="m-0 text-xs text-secondary">
                    Deleting or editing a hierarchy leaves fields already on shelves unchanged. Imported hierarchies are
                    independent copies.
                </p>
            </div>
        </LemonModal>
    )
}
