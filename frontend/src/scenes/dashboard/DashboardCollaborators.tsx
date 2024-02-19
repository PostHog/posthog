import { IconLock, IconTrash, IconUnlock } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { usersLemonSelectOptions } from 'lib/components/UserSelectItem'
import { DashboardPrivilegeLevel, DashboardRestrictionLevel, privilegeLevelToName } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSelect, LemonSelectOptions } from 'lib/lemon-ui/LemonSelect'
import { LemonSelectMultiple } from 'lib/lemon-ui/LemonSelectMultiple/LemonSelectMultiple'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { AvailableFeature, DashboardType, FusedDashboardCollaboratorType, UserType } from '~/types'

import { dashboardCollaboratorsLogic } from './dashboardCollaboratorsLogic'

export const DASHBOARD_RESTRICTION_OPTIONS: LemonSelectOptions<DashboardRestrictionLevel> = [
    {
        value: DashboardRestrictionLevel.EveryoneInProjectCanEdit,
        label: 'Everyone in the project can edit',
        icon: <IconUnlock />,
    },
    {
        value: DashboardRestrictionLevel.OnlyCollaboratorsCanEdit,
        label: 'Only those invited to this dashboard can edit',
        icon: <IconLock />,
    },
]

export function DashboardCollaboration({ dashboardId }: { dashboardId: DashboardType['id'] }): JSX.Element | null {
    const { dashboard, dashboardLoading, canEditDashboard, canRestrictDashboard } = useValues(dashboardLogic)
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
                        <LemonBanner type="info" className="mb-4">
                            {canEditDashboard
                                ? "You aren't allowed to change the restriction level – only the dashboard owner and project admins can."
                                : "You aren't allowed to change sharing settings – only dashboard collaborators with edit settings can."}
                        </LemonBanner>
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
                        fullWidth
                        disabled={!canRestrictDashboard}
                    />
                    {dashboard.restriction_level > DashboardRestrictionLevel.EveryoneInProjectCanEdit && (
                        <div className="mt-4">
                            <h5>Collaborators</h5>
                            {canEditDashboard && (
                                <div className="flex gap-2">
                                    <div className="flex-1">
                                        <LemonSelectMultiple
                                            placeholder="Search for team members to add…"
                                            value={explicitCollaboratorsToBeAdded}
                                            loading={explicitCollaboratorsLoading}
                                            onChange={(newValues: string[]) =>
                                                setExplicitCollaboratorsToBeAdded(newValues)
                                            }
                                            filterOption={true}
                                            mode="multiple"
                                            data-attr="subscribed-emails"
                                            options={usersLemonSelectOptions(addableMembers, 'uuid')}
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
                            <h5 className="mt-4">Project members with access</h5>
                            <div className="mt-2 pb-2 rounded overflow-y-auto max-h-80">
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
        <div className="flex items-center justify-between mt-2 pl-2 h-8">
            <ProfilePicture user={user} size="md" showName />
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
                <div className="flex items-center gap-2">
                    <span className="rounded bg-primary-alt-highlight p-1">{privilegeLevelName}</span>
                    {deleteCollaborator && wasInvited && (
                        <LemonButton
                            icon={<IconTrash />}
                            onClick={() => deleteCollaborator(user.uuid)}
                            tooltip={wasInvited ? 'Remove invited collaborator' : null}
                            size="small"
                        />
                    )}
                </div>
            </Tooltip>
        </div>
    )
}
