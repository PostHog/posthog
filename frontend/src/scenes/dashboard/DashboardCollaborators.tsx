import React from 'react'
import { useActions, useValues } from 'kea'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { LemonButton } from 'lib/components/LemonButton'
import { IconCancel, IconLock, IconLockOpen } from 'lib/components/icons'
import { AvailableFeature, DashboardType, FusedDashboardCollaboratorType, UserType } from '~/types'
import { DashboardRestrictionLevel, privilegeLevelToName, DashboardPrivilegeLevel } from 'lib/constants'
import { LemonSelect, LemonSelectOptions } from 'lib/components/LemonSelect'
import { dashboardCollaboratorsLogic } from './dashboardCollaboratorsLogic'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { Tooltip } from 'lib/components/Tooltip'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { AlertMessage } from 'lib/components/AlertMessage'
import { LemonSelectMultiple } from 'lib/components/LemonSelectMultiple/LemonSelectMultiple'
import { usersLemonSelectOptions } from 'lib/components/UserSelectItem'

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

export function DashboardCollaboration({ dashboardId }: { dashboardId: DashboardType['id'] }): JSX.Element | null {
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
                <PayGateMini feature={AvailableFeature.DASHBOARD_PERMISSIONING}>
                    {(!canEditDashboard || !canRestrictDashboard) && (
                        <AlertMessage type="info">
                            {canEditDashboard
                                ? "You aren't allowed to change the restriction level – only the dashboard owner and project admins can."
                                : "You aren't allowed to change sharing settings – only dashboard collaborators with edit settings can."}
                        </AlertMessage>
                    )}
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
                        fullWidth
                        disabled={!canRestrictDashboard}
                    />
                    {dashboard.restriction_level > DashboardRestrictionLevel.EveryoneInProjectCanEdit && (
                        <div className="mt">
                            <h4>Collaborators</h4>
                            {canEditDashboard && (
                                <div className="flex gap-05">
                                    <div style={{ flex: 1 }}>
                                        <LemonSelectMultiple
                                            placeholder="Search for team members to add…"
                                            value={explicitCollaboratorsToBeAdded}
                                            loading={explicitCollaboratorsLoading}
                                            onChange={(newValues) => setExplicitCollaboratorsToBeAdded(newValues)}
                                            filterOption={false}
                                            mode="multiple"
                                            data-attr="subscribed-emails"
                                            options={usersLemonSelectOptions(addableMembers)}
                                        />
                                    </div>
                                    <LemonButton
                                        type="primary"
                                        loading={explicitCollaboratorsLoading}
                                        disabled={explicitCollaboratorsToBeAdded.length === 0}
                                        onClick={() => addExplicitCollaborators()}
                                    >
                                        Add
                                    </LemonButton>
                                </div>
                            )}
                            <h5 style={{ marginTop: '1rem' }}>Project members with access</h5>
                            <div
                                className="mt-05"
                                style={{
                                    maxHeight: 300,
                                    overflowY: 'auto',
                                    background: 'var(--bg-side)',
                                    paddingBottom: '0.5rem',
                                    paddingRight: '0.5rem',
                                    borderRadius: 4,
                                }}
                            >
                                {allCollaborators.map((collaborator) => (
                                    <CollaboratorRow
                                        key={collaborator.user.uuid}
                                        collaborator={collaborator}
                                        deleteCollaborator={canEditDashboard ? deleteExplicitCollaborator : undefined}
                                    />
                                ))}
                            </div>
                        </div>
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

    const wasInvited = level <= DashboardPrivilegeLevel.CanEdit // Higher levels come from implicit privileges
    const privilegeLevelName = privilegeLevelToName[level]

    return (
        <div className="CollaboratorRow">
            <ProfilePicture email={user.email} name={user.first_name} size="md" showName />
            <Tooltip
                title={
                    !wasInvited
                        ? `${user.first_name || 'This person'} ${
                              level === DashboardPrivilegeLevel._Owner
                                  ? 'created the dashboard'
                                  : 'is a project administrator'
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
                            size="small"
                        />
                    )}
                </div>
            </Tooltip>
        </div>
    )
}
