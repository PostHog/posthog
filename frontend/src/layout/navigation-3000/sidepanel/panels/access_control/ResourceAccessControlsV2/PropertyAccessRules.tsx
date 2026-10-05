import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonTable } from '@posthog/lemon-ui'

import { PROPERTY_ACCESS_LEVEL_OPTIONS } from 'lib/utils/accessControlUtils'

import { AIEventPropertyEnumApi } from 'products/access_control/frontend/generated/api.schemas'

import { AccessPropertyRule, accessDetailLogic } from './accessDetailLogic'
import { AccessDetailSection } from './AccessDetailSection'
import { addPropertyRestrictionModalLogic } from './addPropertyRestrictionModalLogic'
import { AddPropertyRuleModal } from './AddPropertyRuleModal'
import type { ScopeType } from './types'

export interface PropertyAccessRulesProps {
    projectId: string
    scopeType: ScopeType
    subjectId: string
    /** How the subject is called in copy, e.g. "member" or "role". */
    subjectNoun: string
    canEdit: boolean
    /** Shown instead of the generic tooltip when editing is blocked for a subject-specific reason. */
    cannotEditReason?: string
}

/** The subject's own property restrictions, editable in place. */
export function PropertyAccessRules({
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

    return (
        <AccessDetailSection
            title="Property rules"
            description={
                scopeType === 'default'
                    ? 'Property access that applies to everyone without a rule of their own. Default for every property is read & write.'
                    : `This ${subjectNoun}'s access to specific properties. Default for every property is read & write.`
            }
        >
            <AddPropertyRuleModal projectId={projectId} scopeType={scopeType} subjectId={subjectId} />
            <LemonTable
                loading={propertiesLoading}
                columns={[
                    {
                        title: 'Property',
                        key: 'property',
                        render: (_, p: AccessPropertyRule) => (
                            <span className="font-medium">
                                {p.property_type === 'event' &&
                                Object.values(AIEventPropertyEnumApi).some((name) => name === p.property)
                                    ? `${p.property.slice(4)} (${p.property})`
                                    : p.property}
                            </span>
                        ),
                    },
                    {
                        title: 'Type',
                        key: 'type',
                        render: (_, p: AccessPropertyRule) => (
                            <span className="text-secondary">
                                {p.property_type === 'person'
                                    ? 'Person property'
                                    : Object.values(AIEventPropertyEnumApi).some((name) => name === p.property)
                                      ? 'ai_events property'
                                      : 'Event property'}
                            </span>
                        ),
                    },
                    {
                        title: 'Access',
                        key: 'access',
                        align: 'right',
                        render: (_, p: AccessPropertyRule) => (
                            <div className="flex justify-end py-1.5">
                                <LemonSelect
                                    size="small"
                                    value={p.access_level}
                                    dropdownPlacement="bottom-end"
                                    onChange={(level) => setPropertyRule(p.property_definition_id, level)}
                                    disabledReason={editDisabledReason}
                                    options={PROPERTY_ACCESS_LEVEL_OPTIONS}
                                />
                            </div>
                        ),
                    },
                    {
                        title: '',
                        key: 'actions',
                        width: 0,
                        render: (_, p: AccessPropertyRule) => (
                            // Negative margins pull the button into the cell's own padding, which is
                            // wider than an icon button needs
                            <div className="flex justify-end -ml-1 -mr-2">
                                <LemonButton
                                    size="small"
                                    status="danger"
                                    icon={<IconTrash />}
                                    disabledReason={editDisabledReason}
                                    tooltip="Remove the rule. The property's default applies instead."
                                    onClick={() => setPropertyRule(p.property_definition_id, null)}
                                />
                            </div>
                        ),
                    },
                ]}
                dataSource={properties}
                pagination={{ pageSize: 20, hideOnSinglePage: true }}
                emptyState={`No property rules for this ${subjectNoun}.`}
            />
            <div>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPlus />}
                    onClick={openModal}
                    disabledReason={editDisabledReason}
                >
                    Add rule
                </LemonButton>
            </div>
        </AccessDetailSection>
    )
}
