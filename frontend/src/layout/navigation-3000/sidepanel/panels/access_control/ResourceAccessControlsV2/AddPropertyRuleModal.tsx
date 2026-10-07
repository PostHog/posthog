import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInputSelect, LemonLabel, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { PROPERTY_ACCESS_LEVEL_OPTIONS } from 'lib/utils/accessControlUtils'

import { AccessLevelEnumApi } from 'products/access_control/frontend/generated/api.schemas'

import { addPropertyRestrictionModalLogic } from './addPropertyRestrictionModalLogic'
import type { ScopeType } from './types'

function propertyLevelLabel(level: AccessLevelEnumApi): string | JSX.Element {
    return PROPERTY_ACCESS_LEVEL_OPTIONS.find((o) => o.value === level)?.label ?? level
}

export function AddPropertyRuleModal({
    projectId,
    scopeType,
    subjectId,
}: {
    projectId: string
    scopeType: ScopeType
    subjectId: string
}): JSX.Element {
    const logic = addPropertyRestrictionModalLogic({ projectId, scopeType, subjectId })
    const {
        isOpen,
        propertyType,
        propertyId,
        level,
        displayPropertyOptions,
        propertyOptionsLoading,
        existingRule,
        ruleSaving,
    } = useValues(logic)
    const { closeModal, setPropertyType, setSearch, setPropertyId, setLevel, submitRule } = useActions(logic)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeModal}
            closable={!ruleSaving}
            title="Add property rule"
            description={
                scopeType === 'default'
                    ? "Set everyone's access to a specific property."
                    : `Set this ${scopeType === 'role' ? 'role' : 'member'}'s access to a specific property.`
            }
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal} disabled={ruleSaving}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        disabledReason={
                            propertyOptionsLoading
                                ? 'Loading properties'
                                : !propertyId
                                  ? 'Select a property'
                                  : existingRule?.access_level === level
                                    ? 'The rule already has this level'
                                    : undefined
                        }
                        loading={ruleSaving}
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
                        disabled={ruleSaving}
                        data-attr="property-rule-type"
                        options={[
                            { value: 'person', label: 'Person property' },
                            { value: 'event', label: 'Event property' },
                            { value: 'ai', label: 'ai_events property' },
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
                        disabled={ruleSaving}
                        data-attr="property-rule-property"
                        options={displayPropertyOptions.map((o) => ({ key: o.id, label: o.name }))}
                        placeholder="Search by name…"
                    />
                </div>
                <div>
                    <LemonLabel>Access</LemonLabel>
                    <LemonSelect
                        value={level}
                        onChange={setLevel}
                        options={PROPERTY_ACCESS_LEVEL_OPTIONS}
                        disabled={ruleSaving}
                        fullWidth
                    />
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
