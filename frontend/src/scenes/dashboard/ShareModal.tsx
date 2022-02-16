import React from 'react'
import { useActions, useValues } from 'kea'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'
import { urls } from 'scenes/urls'
import { dashboardsModel } from '~/models/dashboardsModel'
import { LemonSwitch } from 'lib/components/LemonSwitch/LemonSwitch'
import { LemonModal } from 'lib/components/LemonModal/LemonModal'
import { LemonButton } from 'lib/components/LemonButton'
import { copyToClipboard } from 'lib/utils'
import { IconCancel, IconCopy, IconLock, IconLockOpen } from 'lib/components/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { AvailableFeature, DashboardType, FusedDashboardCollaboratorType, UserType } from '~/types'
import { FEATURE_FLAGS, DashboardRestrictionLevel, privilegeLevelToName } from 'lib/constants'
import { LemonSelect, LemonSelectOptions } from 'lib/components/LemonSelect'
import { dashboardCollaboratorsLogic } from './dashboardCollaboratorsLogic'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { Button, Select } from 'antd'
import { Tooltip } from 'lib/components/Tooltip'
import { InfoMessage } from 'lib/components/InfoMessage/InfoMessage'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'

export const DASHBOARD_RESTRICTION_OPTIONS: LemonSelectOptions = {
    [DashboardRestrictionLevel.EveryoneInProjectCanEdit]: {
        label: 'Everyone in the project can edit',
        icon: <IconLockOpen />,
    },
    [DashboardRestrictionLevel.OnlyCollaboratorsCanEdit]: {
        label: 'Only those invited to this dashboard can edit',
        icon: <IconLock />,
    },
}

export interface ShareModalProps {
    visible: boolean
    onCancel: () => void
}

export function ShareModal({ visible, onCancel }: ShareModalProps): JSX.Element | null {
    const { dashboardLoading } = useValues(dashboardsModel)
    const { dashboard, canEditDashboard } = useValues(dashboardLogic)
    const { setIsSharedDashboard } = useActions(dashboardLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const shareLink = dashboard ? window.location.origin + urls.sharedDashboard(dashboard.share_token) : ''

    return dashboard ? (
        <LemonModal visible={visible} onCancel={onCancel}>
            {featureFlags[FEATURE_FLAGS.DASHBOARD_PERMISSIONS] && <DashboardCollaboration dashboardId={dashboard.id} />}
            <section>
                <h5>External sharing</h5>
                <LemonSwitch
                    id="share-dashboard-switch"
                    label="Share dashboard publicly"
                    checked={dashboard.is_shared}
                    loading={dashboardLoading}
                    data-attr="share-dashboard-switch"
                    onChange={(active) => {
                        setIsSharedDashboard(dashboard.id, active)
                    }}
                    type="primary"
                    disabled={!canEditDashboard}
                />
                {dashboard.is_shared ? (
                    <>
                        {dashboard.share_token && (
                            <LemonButton
                                data-attr="share-dashboard-link-button"
                                onClick={() => copyToClipboard(shareLink, 'link')}
                                icon={<IconCopy />}
                                style={{ width: '100%', height: '3rem', border: '1px solid var(--border)' }}
                            >
                                Copy shared dashboard link
                            </LemonButton>
                        )}
                        <div>Use this HTML snippet to embed the dashboard on your website:</div>
                        <CodeSnippet language={Language.HTML}>
                            {`<iframe width="100%" height="100%" frameborder="0" src="${shareLink}?embedded" />`}
                        </CodeSnippet>
                    </>
                ) : null}
            </section>
        </LemonModal>
    ) : null
}

function DashboardCollaboration({ dashboardId }: { dashboardId: DashboardType['id'] }): JSX.Element | null {
    const { dashboardLoading } = useValues(dashboardsModel)
    const { dashboard, canEditDashboard, canRestrictDashboard } = useValues(dashboardLogic)
    const { triggerDashboardUpdate } = useActions(dashboardLogic)
    const { allCollaborators, explicitCollaboratorsLoading, addableMembers, explicitCollaboratorsToBeAdded } =
        useValues(dashboardCollaboratorsLogic({ dashboardId }))
    const { deleteExplicitCollaborator, setExplicitCollaboratorsToBeAdded, addExplicitCollaborators } = useActions(
        dashboardCollaboratorsLogic({ dashboardId })
    )

    return (
        dashboard && (
            <>
                <h5>Collaboration settings</h5>
                {(!canEditDashboard || !canRestrictDashboard) && (
                    <InfoMessage>
                        {canEditDashboard
                            ? "You aren't allowed to change the restriction level – only the dashboard owner and project admins can."
                            : "You aren't allowed to change sharing settings – only dashboard collaborators with edit settings can."}
                    </InfoMessage>
                )}
                <PayGateMini feature={AvailableFeature.DASHBOARD_PERMISSIONING} style={{ marginTop: '0.75rem' }}>
                    <section>
                        <LemonSelect
                            value={dashboard.effective_restriction_level}
                            onChange={(newValue) =>
                                triggerDashboardUpdate({
                                    restriction_level: newValue,
                                })
                            }
                            options={DASHBOARD_RESTRICTION_OPTIONS}
                            loading={dashboardLoading}
                            type="stealth"
                            outlined
                            style={{
                                height: '3rem',
                                width: '100%',
                            }}
                            disabled={!canRestrictDashboard}
                        />
                    </section>
                    {dashboard.restriction_level > DashboardRestrictionLevel.EveryoneInProjectCanEdit && (
                        <section>
                            <h5>Collaborators</h5>
                            {canEditDashboard && (
                                <div style={{ display: 'flex', marginBottom: '0.75rem' }}>
                                    {/* TOOD: Use Lemon instead of Ant components here */}
                                    <Select
                                        mode="multiple"
                                        placeholder="Search for team members to add…"
                                        loading={explicitCollaboratorsLoading}
                                        value={explicitCollaboratorsToBeAdded}
                                        onChange={(newValues) => setExplicitCollaboratorsToBeAdded(newValues)}
                                        showArrow
                                        showSearch
                                        style={{ flexGrow: 1 }}
                                    >
                                        {addableMembers.map((user) => (
                                            <Select.Option
                                                key={user.id}
                                                value={user.uuid}
                                                title={`${user.first_name} (${user.email})`}
                                            >
                                                <ProfilePicture
                                                    name={user.first_name}
                                                    email={user.email}
                                                    size="sm"
                                                    style={{ display: 'inline-flex', marginRight: 8 }}
                                                />
                                                {user.first_name} ({user.email})
                                            </Select.Option>
                                        ))}
                                    </Select>
                                    <Button
                                        type="primary"
                                        style={{ flexShrink: 0, marginLeft: '0.5rem' }}
                                        loading={explicitCollaboratorsLoading}
                                        disabled={explicitCollaboratorsToBeAdded.length === 0}
                                        onClick={() => addExplicitCollaborators()}
                                    >
                                        Add
                                    </Button>
                                </div>
                            )}
                            {allCollaborators.map((collaborator) => (
                                <CollaboratorRow
                                    key={collaborator.user.uuid}
                                    collaborator={collaborator}
                                    deleteCollaborator={canEditDashboard ? deleteExplicitCollaborator : undefined}
                                />
                            ))}
                        </section>
                    )}
                </PayGateMini>
            </>
        )
    )
}

function CollaboratorRow({
    collaborator,
    deleteCollaborator,
}: {
    collaborator: FusedDashboardCollaboratorType
    deleteCollaborator?: (userUuid: UserType['uuid']) => void
}): JSX.Element {
    const { user, level } = collaborator

    const wasInvited = typeof level === 'number'
    const privilegeLevelName = privilegeLevelToName(level)

    return (
        <div className="CollaboratorRow">
            <ProfilePicture email={user.email} name={user.first_name} size="md" showName />
            <Tooltip
                title={
                    !wasInvited
                        ? `${user.first_name || 'This person'} ${
                              level === 'owner' ? 'created the dashboard' : 'is a project administrator'
                          }`
                        : null
                }
                placement="left"
            >
                <div className="CollaboratorRow__details">
                    <span>{!wasInvited ? <b>{privilegeLevelName}</b> : privilegeLevelName}</span>
                    {deleteCollaborator && (
                        <LemonButton
                            icon={<IconCancel />}
                            onClick={() => deleteCollaborator(user.uuid)}
                            type="stealth"
                            tooltip={wasInvited ? 'Remove invited collaborator' : null}
                            disabled={!wasInvited}
                            status="danger"
                            compact
                        />
                    )}
                </div>
            </Tooltip>
        </div>
    )
}
