import { useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import {
    PredicateFixAction,
    PredicateIndexUsage,
    PredicateQuickfix,
    PredicateScope,
} from '~/queries/schema/schema-general'

// Longer than this and the label stops being readable at a glance, so it names the action instead.
const MAX_LITERAL_IN_LABEL = 24

// The definitions list filters by `type`; group properties would also need a group type index the
// report does not carry, so they get no link.
const DEFINITION_LIST_TYPES: Partial<Record<PredicateScope, string>> = {
    [PredicateScope.Event]: 'event',
    [PredicateScope.Person]: 'person',
}

interface QueryIndexUsageFixActionsProps {
    predicate: PredicateIndexUsage
    /** The report describes older text than the editor holds, so a query edit would land in the wrong place. */
    stale?: boolean
    onApplyQuickfix?: (quickfix: PredicateQuickfix) => void
    onFixWithAI?: (prompt: string) => void
    fixWithAILoading?: boolean
}

export function QueryIndexUsageFixActions({
    predicate,
    stale,
    onApplyQuickfix,
    onFixWithAI,
    fixWithAILoading,
}: QueryIndexUsageFixActionsProps): JSX.Element | null {
    const { user } = useValues(userLogic)

    if (predicate.fix_action === PredicateFixAction.EditQuery) {
        const staleReason = stale
            ? 'Still checking the latest version of this query. Try again in a moment.'
            : undefined
        if (predicate.quickfix && onApplyQuickfix) {
            const quickfix = predicate.quickfix
            // An IN list produces a replacement as long as the list, which would widen the row and
            // push the table into sideways scroll in a narrow pane. The tooltip keeps the full text.
            const showsLiteral = quickfix.text.length <= MAX_LITERAL_IN_LABEL
            return (
                <div className="flex">
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        disabledReason={staleReason}
                        tooltip={showsLiteral ? undefined : quickfix.text}
                        onClick={() => onApplyQuickfix(quickfix)}
                        data-attr="sql-editor-index-usage-apply-quickfix"
                    >
                        {showsLiteral ? `Replace with ${quickfix.text}` : 'Write the values as text'}
                    </LemonButton>
                </div>
            )
        }
        if (predicate.ai_fix_prompt && onFixWithAI) {
            const prompt = predicate.ai_fix_prompt
            return (
                <div className="flex">
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        loading={fixWithAILoading}
                        disabledReason={staleReason}
                        onClick={() => onFixWithAI(prompt)}
                        data-attr="sql-editor-index-usage-fix-with-ai"
                    >
                        Fix with AI
                    </LemonButton>
                </div>
            )
        }
        return null
    }

    if (predicate.fix_action === PredicateFixAction.EditPropertyType) {
        const type = DEFINITION_LIST_TYPES[predicate.scope]
        if (!type) {
            return null
        }
        return (
            <div className="flex">
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    to={combineUrl(urls.propertyDefinitions(type), { property: predicate.property_name }).url}
                    targetBlank
                    data-attr="sql-editor-index-usage-edit-property-type"
                >
                    Edit property type
                </LemonButton>
            </div>
        )
    }

    // Materialization is a staff-only page, so everyone else keeps the prose and no dead link.
    if (predicate.fix_action === PredicateFixAction.Materialize && user?.is_staff) {
        return (
            <div className="flex">
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    to={urls.materializedColumns()}
                    targetBlank
                    data-attr="sql-editor-index-usage-materialize"
                >
                    Open materialized columns
                </LemonButton>
            </div>
        )
    }

    return null
}
