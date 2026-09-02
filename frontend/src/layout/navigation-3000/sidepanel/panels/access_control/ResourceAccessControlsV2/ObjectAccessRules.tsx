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
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { toSentenceCase } from 'lib/utils/strings'

import { AccessLevelSelect } from '../AccessLevelSelect'
import { accessControlsLogic } from './accessControlsLogic'
import { AccessObjectRule, accessDetailLogic, objectRuleUrl } from './accessDetailLogic'
import { AccessDetailSection } from './AccessDetailSection'
import { addObjectOverrideModalLogic } from './addObjectOverrideModalLogic'
import { humanizeAccessControlLevel } from './helpers'
import { ScopeIcon } from './ScopeIcon'
import type { ScopeType } from './types'

export interface ObjectAccessRulesProps {
    projectId: string
    scopeType: ScopeType
    subjectId: string
    /** How the subject is called in copy, e.g. "member" or "role". */
    subjectNoun: string
    canEdit: boolean
    /** Shown instead of the generic tooltip when editing is blocked for a subject-specific reason. */
    cannotEditReason?: string
}

/** The subject's own object-level rules, editable in place. */
export function ObjectAccessRules({
    projectId,
    scopeType,
    subjectId,
    subjectNoun,
    canEdit,
    cannotEditReason,
}: ObjectAccessRulesProps): JSX.Element {
    const { objects, objectsLoading, ruleSaving } = useValues(accessDetailLogic({ projectId, scopeType, subjectId }))
    const { objectRuleResourceOptions, availableResourceLevels } = useValues(accessControlsLogic({ projectId }))
    const { setObjectRule } = useActions(accessDetailLogic({ projectId, scopeType, subjectId }))
    const { openModal } = useActions(addObjectOverrideModalLogic({ projectId, scopeType, subjectId }))

    const editDisabledReason = !canEdit
        ? (cannotEditReason ?? 'You cannot edit this')
        : ruleSaving
          ? 'Saving…'
          : undefined

    return (
        <AccessDetailSection
            title="One-off access overrides"
            description={
                scopeType === 'default'
                    ? 'Specific dashboards, insights, notebooks and warehouse tables everyone is given access to, or blocked from, regardless of the defaults above.'
                    : `Specific dashboards, insights, notebooks and warehouse tables this ${subjectNoun} is given access to, or blocked from, regardless of the tools above.`
            }
        >
            <AddObjectRuleModal projectId={projectId} scopeType={scopeType} subjectId={subjectId} />
            <LemonTable
                loading={objectsLoading}
                columns={[
                    {
                        title: 'Object',
                        key: 'object',
                        render: (_, o: AccessObjectRule) => {
                            const href = objectRuleUrl(o)
                            const label = href ? <Link to={href}>{o.name}</Link> : o.name
                            return (
                                <div className="flex items-center gap-2">
                                    <Tooltip title={toSentenceCase(o.resource.replace(/_/g, ' '))}>
                                        <span className="text-muted-alt flex items-center">
                                            <ScopeIcon scope={o.resource} />
                                        </span>
                                    </Tooltip>
                                    <span className="font-medium">{label}</span>
                                </div>
                            )
                        },
                    },
                    {
                        title: 'Access',
                        key: 'access',
                        align: 'right',
                        render: (_, o: AccessObjectRule) => {
                            const resourceLevels = objectRuleResourceOptions.find((r) => r.resource === o.resource)
                            return (
                                <div className="flex justify-end py-1.5">
                                    <AccessLevelSelect
                                        size="small"
                                        dropdownPlacement="bottom-end"
                                        level={o.access_level}
                                        levels={resourceLevels?.available_access_levels ?? availableResourceLevels}
                                        minimumLevel={resourceLevels?.minimum_access_level}
                                        onChange={(level) => setObjectRule(o.resource, o.resource_id, level)}
                                        disabledReason={editDisabledReason}
                                    />
                                </div>
                            )
                        },
                    },
                    {
                        title: '',
                        key: 'actions',
                        width: 0,
                        render: (_, o: AccessObjectRule) => (
                            // Negative margins pull the button into the cell's own padding, which is
                            // wider than an icon button needs
                            <div className="flex justify-end -ml-1 -mr-2">
                                <LemonButton
                                    size="small"
                                    status="danger"
                                    icon={<IconTrash />}
                                    disabledReason={editDisabledReason}
                                    tooltip="Remove the rule"
                                    onClick={() => setObjectRule(o.resource, o.resource_id, null)}
                                />
                            </div>
                        ),
                    },
                ]}
                dataSource={objects}
                pagination={{ pageSize: 20, hideOnSinglePage: true }}
                emptyState={`No one-off access overrides for this ${subjectNoun}.`}
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

function AddObjectRuleModal({
    projectId,
    scopeType,
    subjectId,
}: {
    projectId: string
    scopeType: ScopeType
    subjectId: string
}): JSX.Element {
    const logic = addObjectOverrideModalLogic({ projectId, scopeType, subjectId })
    const {
        isOpen,
        resource,
        objectId,
        level,
        displayObjectOptions,
        objectOptionsLoading,
        existingRule,
        objectInputKey,
    } = useValues(logic)
    const { objectRuleResourceOptions, availableResourceLevels } = useValues(accessControlsLogic({ projectId }))
    const { closeModal, setResource, setSearch, setObjectId, setLevel, submitRule } = useActions(logic)

    const resourceLevels = objectRuleResourceOptions.find((r) => r.resource === resource)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeModal}
            title="Add access rule"
            description={
                scopeType === 'default'
                    ? "Grant or restrict everyone's access to a specific object."
                    : `Grant or restrict this ${scopeType === 'role' ? 'role' : 'member'}'s access to a specific object.`
            }
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        disabledReason={
                            !objectId
                                ? 'Select an object'
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
                        value={resource}
                        onChange={setResource}
                        options={objectRuleResourceOptions.map((r) => ({
                            value: r.resource,
                            label: toSentenceCase(r.resource.replace(/_/g, ' ')),
                        }))}
                        fullWidth
                    />
                </div>
                <div>
                    <LemonLabel>Object</LemonLabel>
                    <LemonInputSelect
                        key={objectInputKey}
                        mode="single"
                        // The backend already searched; filtering again locally would hide its
                        // results whenever the typed text isn't part of the object's name
                        disableFiltering
                        value={objectId ? [objectId] : []}
                        onChange={(values) => setObjectId(values[0] ?? null)}
                        onInputChange={setSearch}
                        loading={objectOptionsLoading}
                        options={displayObjectOptions.map((o) => ({ key: o.id, label: o.name }))}
                        placeholder="Search by name or paste URL"
                    />
                </div>
                <div>
                    <LemonLabel>Access</LemonLabel>
                    <AccessLevelSelect
                        level={level}
                        levels={resourceLevels?.available_access_levels ?? availableResourceLevels}
                        minimumLevel={resourceLevels?.minimum_access_level}
                        onChange={(newLevel) => newLevel && setLevel(newLevel)}
                        fullWidth
                    />
                </div>
                {existingRule ? (
                    <LemonBanner type="warning">
                        "{existingRule.name}" already has a rule.{' '}
                        {existingRule.access_level === level
                            ? `It's already set to ${humanizeAccessControlLevel(level)}.`
                            : `Saving updates it from ${humanizeAccessControlLevel(
                                  existingRule.access_level
                              )} to ${humanizeAccessControlLevel(level)}.`}
                    </LemonBanner>
                ) : null}
            </div>
        </LemonModal>
    )
}
