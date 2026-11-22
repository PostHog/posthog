import type { CellContext, ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { createContext, useContext } from 'react'

import { IconPlus, IconTrash } from '@posthog/icons'
import { Button, DataTable, Skeleton, Text } from '@posthog/quill'

import { AIEventPropertyEnumApi, AccessLevelEnumApi } from 'products/access_control/frontend/generated/api.schemas'

import { AccessPropertyRule, accessDetailLogic } from './accessDetailLogic'
import { addPropertyRestrictionModalLogic } from './addPropertyRestrictionModalLogic'
import { PROPERTY_RULE_LEVEL_OPTIONS } from './helpers'
import type { PropertyAccessRulesProps } from './PropertyAccessRules'
import { QuillAccessDetailSection } from './QuillAccessDetailSection'
import { QuillAddPropertyRuleModal } from './QuillAddPropertyRuleModal'
import { QuillLevelSelect } from './QuillLevelSelect'

const RULES_PER_PAGE = 20

function isAIEventProperty(rule: AccessPropertyRule): boolean {
    return Object.values(AIEventPropertyEnumApi).some((name) => name === rule.property)
}

function propertyLabel(rule: AccessPropertyRule): string {
    return rule.property_type === 'event' && isAIEventProperty(rule)
        ? `${rule.property.slice(4)} (${rule.property})`
        : rule.property
}

interface PropertyRuleRowEditing {
    editDisabledReason: string | undefined
    onSetLevel: (rule: AccessPropertyRule, level: AccessLevelEnumApi | null) => void
}

// DataTable renders each cell function as a component, so the cells live at module scope and read the edit state
// from context. Rebuilding them when a save starts would remount the access select and drop keyboard focus.
const PropertyRuleRowEditingContext = createContext<PropertyRuleRowEditing | null>(null)

function usePropertyRuleRowEditing(): PropertyRuleRowEditing {
    const rowEditing = useContext(PropertyRuleRowEditingContext)
    if (!rowEditing) {
        throw new Error('Property rule cells must render inside PropertyRuleRowEditingContext')
    }
    return rowEditing
}

function PropertyCell({ row }: CellContext<AccessPropertyRule, unknown>): JSX.Element {
    return (
        <Text size="xs" weight="medium" render={<span />}>
            {propertyLabel(row.original)}
        </Text>
    )
}

function TypeCell({ row }: CellContext<AccessPropertyRule, unknown>): JSX.Element {
    return (
        <Text size="xs" variant="muted" render={<span />}>
            {row.original.property_type === 'person'
                ? 'Person property'
                : isAIEventProperty(row.original)
                  ? 'ai_events property'
                  : 'Event property'}
        </Text>
    )
}

function AccessCell({ row }: CellContext<AccessPropertyRule, unknown>): JSX.Element {
    const { editDisabledReason, onSetLevel } = usePropertyRuleRowEditing()

    return (
        <QuillLevelSelect
            value={row.original.access_level}
            options={PROPERTY_RULE_LEVEL_OPTIONS}
            onChange={(level) => onSetLevel(row.original, level)}
            disabledReason={editDisabledReason}
            aria-label={`Access to ${propertyLabel(row.original)}`}
        />
    )
}

function RemoveCell({ row }: CellContext<AccessPropertyRule, unknown>): JSX.Element {
    const { editDisabledReason, onSetLevel } = usePropertyRuleRowEditing()

    return (
        <Button
            size="icon"
            aria-label="Remove the rule"
            tooltip="Remove the rule. The property's default applies instead."
            disabledReason={editDisabledReason}
            onClick={() => onSetLevel(row.original, null)}
        >
            <IconTrash />
        </Button>
    )
}

const COLUMNS: ColumnDef<AccessPropertyRule>[] = [
    { id: 'property', header: 'Property', meta: { expand: true }, enableSorting: false, cell: PropertyCell },
    { id: 'type', header: 'Type', enableSorting: false, cell: TypeCell },
    { id: 'access', header: 'Access', meta: { align: 'right' }, enableSorting: false, cell: AccessCell },
    { id: 'actions', header: '', meta: { align: 'right' }, enableSorting: false, cell: RemoveCell },
]

export function QuillPropertyAccessRules({
    projectId,
    scopeType,
    subjectId,
    subjectNoun,
    canEdit,
    cannotEditReason,
}: PropertyAccessRulesProps): JSX.Element {
    const { properties, propertiesLoading, ruleSaving } = useValues(
        accessDetailLogic({ projectId, scopeType, subjectId })
    )
    const { setPropertyRule } = useActions(accessDetailLogic({ projectId, scopeType, subjectId }))
    const { openModal } = useActions(addPropertyRestrictionModalLogic({ projectId, scopeType, subjectId }))

    const editDisabledReason = !canEdit
        ? (cannotEditReason ?? 'You cannot edit this')
        : ruleSaving
          ? 'Saving…'
          : undefined

    const rowEditing: PropertyRuleRowEditing = {
        editDisabledReason,
        onSetLevel: (rule, level) => setPropertyRule(rule.property_definition_id, level),
    }

    return (
        <QuillAccessDetailSection
            title="Property rules"
            description={
                scopeType === 'default'
                    ? 'Property access that applies to everyone without a rule of their own. Default for every property is read & write.'
                    : `This ${subjectNoun}'s access to specific properties. Default for every property is read & write.`
            }
        >
            <QuillAddPropertyRuleModal projectId={projectId} scopeType={scopeType} subjectId={subjectId} />
            {propertiesLoading && properties.length === 0 ? (
                <Skeleton className="h-24 w-full" />
            ) : (
                <PropertyRuleRowEditingContext.Provider value={rowEditing}>
                    <DataTable
                        columns={COLUMNS}
                        data={properties}
                        getRowId={(rule) => rule.property_definition_id}
                        fullWidth
                        pageSize={properties.length > RULES_PER_PAGE ? RULES_PER_PAGE : undefined}
                        empty={
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                {`No property rules for this ${subjectNoun}.`}
                            </Text>
                        }
                    />
                </PropertyRuleRowEditingContext.Provider>
            )}
            <div className="flex">
                <Button variant="outline" onClick={openModal} disabledReason={editDisabledReason}>
                    <IconPlus />
                    Add rule
                </Button>
            </div>
        </QuillAccessDetailSection>
    )
}
