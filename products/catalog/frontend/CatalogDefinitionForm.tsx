import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonInputSelect, LemonTextArea } from '@posthog/lemon-ui'

import { CatalogDefinitionColumnsTable } from './CatalogDefinitionColumnsTable'
import { catalogDefinitionSceneLogic } from './catalogDefinitionSceneLogic'

interface Props {
    /** Stack fields vertically and trim hints — for the narrow side panel. */
    compact?: boolean
    /** Hide the in-form save/discard row when the parent renders its own (e.g. as a sticky footer). */
    hideActions?: boolean
}

/**
 * Editable fields for a CatalogNode: tags, description, semantic role, business
 * domain, and the columns table. Mount the surrounding `catalogDefinitionSceneLogic`
 * via `<BindLogic>` so this form can be reused both in the full-page detail scene
 * and in the floating side panel on the graph view.
 */
export function CatalogDefinitionForm({ compact = false, hideActions = false }: Props = {}): JSX.Element | null {
    const { definition, pendingEdits } = useValues(catalogDefinitionSceneLogic)
    const { setEdits } = useActions(catalogDefinitionSceneLogic)

    if (!definition) {
        return null
    }

    const tags = pendingEdits.tags ?? definition.tags ?? []
    const description = pendingEdits.synthetic_description ?? definition.description ?? ''
    const semanticRole = pendingEdits.semantic_role ?? definition.semantic_role ?? ''
    const businessDomain = pendingEdits.business_domain ?? definition.business_domain ?? ''

    return (
        <div className={compact ? 'flex flex-col gap-3' : 'flex flex-col gap-6'}>
            <Field label="Tags" compact={compact}>
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    value={tags}
                    options={tags.map((t) => ({ key: t, label: t }))}
                    onChange={(next) => setEdits({ tags: next })}
                    placeholder="Add a tag and press enter"
                />
            </Field>
            <Field
                label="Description"
                hint={
                    compact ? undefined : 'What this table contains, when to use it, and caveats. Markdown supported.'
                }
                compact={compact}
            >
                <LemonTextArea
                    value={description}
                    onChange={(next) => setEdits({ synthetic_description: next })}
                    placeholder="Describe what's in this table"
                    minRows={compact ? 3 : 4}
                />
            </Field>
            <div className={compact ? 'flex flex-col gap-3' : 'grid grid-cols-2 gap-4'}>
                <Field
                    label="Semantic role"
                    hint={compact ? undefined : 'fact · dimension · bridge · event_source · identity'}
                    compact={compact}
                >
                    <LemonInput
                        value={semanticRole}
                        onChange={(next) => setEdits({ semantic_role: next })}
                        placeholder={compact ? 'fact · dimension · bridge …' : 'e.g. fact'}
                    />
                </Field>
                <Field
                    label="Business domain"
                    hint={compact ? undefined : 'billing · crm · product_usage · support'}
                    compact={compact}
                >
                    <LemonInput
                        value={businessDomain}
                        onChange={(next) => setEdits({ business_domain: next })}
                        placeholder={compact ? 'billing · crm · product_usage …' : 'e.g. billing'}
                    />
                </Field>
            </div>
            <Field
                label="Columns"
                hint={
                    compact
                        ? undefined
                        : "Edit a column's semantic type, PII class, or description inline. Save per row."
                }
                compact={compact}
            >
                <CatalogDefinitionColumnsTable compact={compact} />
            </Field>
            {!hideActions && <CatalogDefinitionFormActions />}
        </div>
    )
}

/**
 * Save / Discard buttons for the catalog definition form. Pulled out so the
 * side panel can render them as a sticky footer outside the scroll zone.
 * Saves all pending edits in one click — definition fields plus every dirty column.
 */
export function CatalogDefinitionFormActions(): JSX.Element {
    const { isDirty } = useValues(catalogDefinitionSceneLogic)
    const { discardChanges, saveChanges } = useActions(catalogDefinitionSceneLogic)

    return (
        <div className="flex justify-end gap-2">
            <LemonButton type="tertiary" onClick={discardChanges} disabledReason={isDirty ? undefined : 'No changes'}>
                Discard
            </LemonButton>
            <LemonButton type="primary" onClick={saveChanges} disabledReason={isDirty ? undefined : 'No changes'}>
                Save changes
            </LemonButton>
        </div>
    )
}

function Field({
    label,
    hint,
    compact,
    children,
}: {
    label: string
    hint?: string
    compact?: boolean
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-baseline gap-2">
                <span className={compact ? 'text-xs font-medium' : 'text-sm font-medium'}>{label}</span>
                {hint && <span className="text-xs text-secondary">{hint}</span>}
            </div>
            {children}
        </div>
    )
}
