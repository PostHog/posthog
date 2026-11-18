import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { Button, DataTable, Skeleton, Text } from '@posthog/quill'

import { AIEventPropertyEnumApi } from 'products/access_control/frontend/generated/api.schemas'

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

    const columns: ColumnDef<AccessPropertyRule>[] = [
        {
            id: 'property',
            header: 'Property',
            meta: { expand: true },
            enableSorting: false,
            cell: ({ row }) => (
                <Text size="xs" weight="medium" render={<span />}>
                    {row.original.property_type === 'event' && isAIEventProperty(row.original)
                        ? `${row.original.property.slice(4)} (${row.original.property})`
                        : row.original.property}
                </Text>
            ),
        },
        {
            id: 'type',
            header: 'Type',
            enableSorting: false,
            cell: ({ row }) => (
                <Text size="xs" variant="muted" render={<span />}>
                    {row.original.property_type === 'person'
                        ? 'Person property'
                        : isAIEventProperty(row.original)
                          ? 'ai_events property'
                          : 'Event property'}
                </Text>
            ),
        },
        {
            id: 'access',
            header: 'Access',
            meta: { align: 'right' },
            enableSorting: false,
            cell: ({ row }) => (
                <QuillLevelSelect
                    value={row.original.access_level}
                    options={PROPERTY_RULE_LEVEL_OPTIONS}
                    onChange={(level) => setPropertyRule(row.original.property_definition_id, level)}
                    disabledReason={editDisabledReason}
                />
            ),
        },
        {
            id: 'actions',
            header: '',
            meta: { align: 'right' },
            enableSorting: false,
            cell: ({ row }) => (
                <Button
                    size="icon"
                    aria-label="Remove the rule"
                    tooltip="Remove the rule. The property's default applies instead."
                    disabledReason={editDisabledReason}
                    onClick={() => setPropertyRule(row.original.property_definition_id, null)}
                >
                    <IconTrash />
                </Button>
            ),
        },
    ]

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
                <DataTable
                    columns={columns}
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
