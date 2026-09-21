import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInputSelect,
    LemonLabel,
    LemonModal,
    LemonSelect,
    LemonTable,
} from '@posthog/lemon-ui'

import { PROPERTY_ACCESS_LEVEL_OPTIONS } from 'lib/utils/accessControlUtils'

import { AccessLevelEnumApi } from 'products/access_control/frontend/generated/api.schemas'

import { AccessPropertyRule, accessDetailLogic } from './accessDetailLogic'
import { AccessDetailSection } from './AccessDetailSection'
import { addPropertyRestrictionModalLogic } from './addPropertyRestrictionModalLogic'
import type { ScopeType } from './types'

function propertyLevelLabel(level: AccessLevelEnumApi): string | JSX.Element {
    return PROPERTY_ACCESS_LEVEL_OPTIONS.find((o) => o.value === level)?.label ?? level
}

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
                        render: (_, p: AccessPropertyRule) => <span className="font-medium">{p.property}</span>,
                    },
                    {
                        title: 'Type',
                        key: 'type',
                        render: (_, p: AccessPropertyRule) => (
                            <span className="text-secondary">
                                {p.property_type === 'person' ? 'Person property' : 'Event property'}
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

function AddPropertyRuleModal({
    projectId,
    scopeType,
    subjectId,
}: {
    projectId: string
    scopeType: ScopeType
    subjectId: string
}): JSX.Element {
    const logic = addPropertyRestrictionModalLogic({ projectId, scopeType, subjectId })
    const { isOpen, propertyType, propertyId, level, displayPropertyOptions, propertyOptionsLoading, existingRule } =
        useValues(logic)
    const { closeModal, setPropertyType, setSearch, setPropertyId, setLevel, submitRule } = useActions(logic)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeModal}
            title="Add property rule"
            description={
                scopeType === 'default'
                    ? "Set everyone's access to a specific property."
                    : `Set this ${scopeType === 'role' ? 'role' : 'member'}'s access to a specific property.`
            }
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        disabledReason={
                            !propertyId
                                ? 'Select a property'
                                : existingRule?.access_level === level
                                  ? 'The rule already has this level'
                                  : undefined
                        }
                        onClick={submitRule}
                    >
                        {existingRule ? 'Update rule' : 'Add rule'}
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-3 min-w-[24rem]">
                <div>
                    <LemonLabel>Type</LemonLabel>
                    <LemonSelect
                        value={propertyType}
                        onChange={setPropertyType}
                        options={[
                            { value: 'person', label: 'Person property' },
                            { value: 'event', label: 'Event property' },
                        ]}
                        fullWidth
                    />
                </div>
                <div>
                    <LemonLabel>Property</LemonLabel>
                    <LemonInputSelect
                        mode="single"
                        value={propertyId ? [propertyId] : []}
                        onChange={(values) => setPropertyId(values[0] ?? null)}
                        onInputChange={setSearch}
                        loading={propertyOptionsLoading}
                        options={displayPropertyOptions.map((o) => ({ key: o.id, label: o.name }))}
                        placeholder="Search by name…"
                    />
                </div>
                <div>
                    <LemonLabel>Access</LemonLabel>
                    <LemonSelect value={level} onChange={setLevel} options={PROPERTY_ACCESS_LEVEL_OPTIONS} fullWidth />
                </div>
                {existingRule ? (
                    <LemonBanner type="warning">
                        "{existingRule.property}" already has a rule.{' '}
                        {existingRule.access_level === level ? (
                            <>It's already set to {propertyLevelLabel(level)}.</>
                        ) : (
                            <>
                                Saving updates it from {propertyLevelLabel(existingRule.access_level)} to{' '}
                                {propertyLevelLabel(level)}.
                            </>
                        )}
                    </LemonBanner>
                ) : null}
            </div>
        </LemonModal>
    )
}
