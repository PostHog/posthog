import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInputSelect, LemonLabel, LemonModal, LemonSelect, LemonTable, Link } from '@posthog/lemon-ui'

import { toSentenceCase } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { APIScopeObject, AccessControlLevel } from '~/types'

import type { InheritedAccess } from '../accessControlLogic'
import { AccessLevelSelect } from '../AccessLevelSelect'
import { AccessObjectRule, OBJECT_RULE_RESOURCES, accessDetailLogic } from './accessDetailLogic'
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

/** How to name the resource in copy, e.g. "dashboard" or "feature flag". */
function resourceNoun(resource: string): string {
    return (OBJECT_RULE_RESOURCES.find((r) => r.value === resource)?.label ?? resource.replace(/_/g, ' ')).toLowerCase()
}

/** What takes over on this object once the subject's own rule is gone. */
function inheritedFor(o: AccessObjectRule, scopeType: ScopeType, subjectNoun: string): InheritedAccess | null {
    if (!o.inherited_access_level) {
        return null
    }
    const reasons: Record<AccessObjectRule['inherited_access_level_source'], string> = {
        role: 'Based on role permissions for this object',
        resource:
            scopeType === 'default'
                ? `Based on the default for ${resourceNoun(o.resource)}s`
                : `Based on this ${subjectNoun}'s access to ${resourceNoun(o.resource)}s`,
        object_default: 'Based on the default for this object',
        built_in: `Based on the default for ${resourceNoun(o.resource)}s`,
        organization_admin: 'Organization admins always have full access',
    }
    return {
        label: humanizeAccessControlLevel(o.inherited_access_level),
        reason: reasons[o.inherited_access_level_source],
    }
}

/** A link to open the object, for resource types we can address from the stored resource_id. */
function objectUrl(o: AccessObjectRule): string | null {
    switch (o.resource) {
        case 'dashboard':
            return urls.dashboard(o.resource_id)
        case 'feature_flag':
            return urls.featureFlag(o.resource_id)
        case 'experiment':
            return urls.experiment(o.resource_id)
        case 'survey':
            return urls.survey(o.resource_id)
        case 'action':
            return urls.action(o.resource_id)
        case 'warehouse_view':
            return urls.sqlEditor({ view_id: o.resource_id })
        case 'external_data_source':
            return urls.dataWarehouseSource(`managed-${o.resource_id}`)
        case 'warehouse_table':
            // Tables have no page of their own, so open them the way the warehouse UI does — querying them
            return urls.sqlEditor({ query: `SELECT * FROM ${o.name} LIMIT 100` })
        default:
            // insight / notebook pages need a short_id we don't have here — show as plain text
            return null
    }
}

/** The subject's own object-level rules, editable in place. */
export function ObjectAccessRules({
    projectId,
    scopeType,
    subjectId,
    subjectNoun,
    canEdit,
}: ObjectAccessRulesProps): JSX.Element {
    const { objects, objectsLoading } = useValues(accessDetailLogic({ projectId, scopeType, subjectId }))
    const { setObjectRule } = useActions(accessDetailLogic({ projectId, scopeType, subjectId }))
    const { openModal } = useActions(addObjectOverrideModalLogic({ projectId, scopeType, subjectId }))

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
                            const href = objectUrl(o)
                            const label = href ? <Link to={href}>{o.name}</Link> : o.name
                            return (
                                <div className="flex items-center gap-2">
                                    <span className="text-muted-alt flex items-center">
                                        <ScopeIcon scope={o.resource as APIScopeObject} />
                                    </span>
                                    <span className="font-medium">{label}</span>
                                </div>
                            )
                        },
                    },
                    {
                        title: 'Type',
                        key: 'type',
                        render: (_, o: AccessObjectRule) => (
                            <span className="text-secondary">{toSentenceCase(o.resource.replace(/_/g, ' '))}</span>
                        ),
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
                                    disabledReason={!canEdit ? 'You cannot edit this' : undefined}
                                    inherited={inheritedFor(o, scopeType, subjectNoun)}
                                />
                            </div>
                        ),
                    },
                    {
                        title: '',
                        key: 'actions',
                        width: 0,
                        render: (_, o: AccessObjectRule) => {
                            const inherited = inheritedFor(o, scopeType, subjectNoun)
                            return (
                                // Negative margins pull the button into the cell's own padding, which is
                                // wider than an icon button needs
                                <div className="flex justify-end -ml-1 -mr-2">
                                    <LemonButton
                                        size="small"
                                        status="danger"
                                        icon={<IconTrash />}
                                        disabledReason={!canEdit ? 'You cannot edit this' : undefined}
                                        tooltip={
                                            inherited
                                                ? `Remove the rule. ${inherited.label} applies instead, ${inherited.reason.toLowerCase()}.`
                                                : 'Remove the rule'
                                        }
                                        onClick={() => setObjectRule(o.resource, o.resource_id, null)}
                                    />
                                </div>
                            )
                        },
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
    const { isOpen, resource, objectId, level, objectOptions, objectOptionsLoading } = useValues(logic)
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
                        Add rule
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
                        options={OBJECT_RULE_RESOURCES.map((r) => ({ value: r.value, label: r.label }))}
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
                        options={objectOptions.map((o) => ({ key: o.id, label: o.name }))}
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
            </div>
        </LemonModal>
    )
}
