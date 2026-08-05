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

import { resourceTypeToString } from 'lib/utils/accessControlUtils'
import { toSentenceCase } from 'lib/utils/strings'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { AccessLevelSelect } from '../AccessLevelSelect'
import { accessControlsLogic } from './accessControlsLogic'
import { AccessObjectRule, accessDetailLogic, objectRuleUrl } from './accessDetailLogic'
import { AccessDetailSection } from './AccessDetailSection'
import { addObjectOverrideModalLogic } from './addObjectOverrideModalLogic'
import { humanizeAccessControlLevel } from './helpers'
import { ScopeIcon } from './ScopeIcon'
import type { ScopeType } from './types'

const OBJECT_LEVELS: AccessControlLevel[] = [
    AccessControlLevel.None,
    AccessControlLevel.Viewer,
    AccessControlLevel.Editor,
    AccessControlLevel.Manager,
]

export interface ObjectAccessRulesProps {
    projectId: string
    scopeType: ScopeType
    subjectId: string
    /** How the subject is called in copy, e.g. "member" or "role". */
    subjectNoun: string
    canEdit: boolean
}

/** The subject's own object-level rules, editable in place. */
export function ObjectAccessRules({
    projectId,
    scopeType,
    subjectId,
    subjectNoun,
    canEdit,
}: ObjectAccessRulesProps): JSX.Element {
    const { objects, objectsLoading, ruleSaving } = useValues(accessDetailLogic({ projectId, scopeType, subjectId }))
    const { setObjectRule } = useActions(accessDetailLogic({ projectId, scopeType, subjectId }))
    const { openModal } = useActions(addObjectOverrideModalLogic({ projectId, scopeType, subjectId }))

    const editDisabledReason = !canEdit ? 'You cannot edit this' : ruleSaving ? 'Saving…' : undefined

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
                        render: (_, o: AccessObjectRule) => (
                            <div className="flex justify-end py-1.5">
                                <AccessLevelSelect
                                    size="small"
                                    level={o.access_level}
                                    levels={OBJECT_LEVELS}
                                    onChange={(level) => setObjectRule(o.resource, o.resource_id, level)}
                                    disabledReason={editDisabledReason}
                                />
                            </div>
                        ),
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
                    disabledReason={!canEdit ? 'You cannot edit this' : undefined}
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
    const { isOpen, resource, objectId, level, displayObjectOptions, objectOptionsLoading, existingRule } =
        useValues(logic)
    const { objectRuleResourceOptions } = useValues(accessControlsLogic({ projectId }))
    const { closeModal, setResource, setSearch, setObjectId, setLevel, submitRule } = useActions(logic)

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
                        disabledReason={!objectId ? 'Select an object' : undefined}
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
                            value: r,
                            label: toSentenceCase(resourceTypeToString(r as AccessControlResourceType)),
                        }))}
                        fullWidth
                    />
                </div>
                <div>
                    <LemonLabel>Object</LemonLabel>
                    <LemonInputSelect
                        mode="single"
                        value={objectId ? [objectId] : []}
                        onChange={(values) => setObjectId(values[0] ?? null)}
                        onInputChange={setSearch}
                        loading={objectOptionsLoading}
                        options={displayObjectOptions.map((o) => ({ key: o.id, label: o.name }))}
                        placeholder="Search by name…"
                    />
                </div>
                <div>
                    <LemonLabel>Access</LemonLabel>
                    <LemonSelect
                        value={level}
                        onChange={setLevel}
                        options={[
                            { value: AccessControlLevel.None, label: 'No access' },
                            { value: AccessControlLevel.Viewer, label: 'Viewer' },
                            { value: AccessControlLevel.Editor, label: 'Editor' },
                            { value: AccessControlLevel.Manager, label: 'Manager' },
                        ]}
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
