import { LemonButton, LemonSelect, LemonSelectOptions } from "@posthog/lemon-ui";
import { useActions, useValues } from "kea";
import { AlertMessage } from "lib/components/AlertMessage";
import { IconDelete, IconLock, IconLockOpen } from "lib/components/icons";
import { LemonSelectMultiple } from "lib/components/LemonSelectMultiple/LemonSelectMultiple";
import { PayGateMini } from "lib/components/PayGateMini/PayGateMini";
import { ProfilePicture } from "lib/components/ProfilePicture";
import { Tooltip } from "lib/components/Tooltip";
import { usersLemonSelectOptions } from "lib/components/UserSelectItem";
import { FeatureFlagPrivilegeLevel, FeatureFlagRestrictionLevel, privilegeLevelToName } from "lib/constants";
import { AvailableFeature, FusedFeatureFlagCollaboratorType, UserType } from "~/types";
import { featureFlagCollaboratorsLogic } from "./featureFlagCollaboratorsLogic";
import { featureFlagLogic } from "./featureFlagLogic";

export const FEATURE_FLAG_RESTRICTION_OPTIONS: LemonSelectOptions<FeatureFlagRestrictionLevel> = [
    {
        value: FeatureFlagRestrictionLevel.EveryoneInProjectCanEdit,
        label: 'Everyone in the project can edit',
        icon: <IconLockOpen />,
    },
    {
        value: FeatureFlagRestrictionLevel.OnlyCollaboratorsCanEdit,
        label: 'Only those invited to this dashboard can edit',
        icon: <IconLock />,
    },
]

export function FeatureFlagSettings({ id }: { id: number }): JSX.Element {
    return (
        <FeatureFlagCollaboration featureFlagId={id} />
    )
}

export function FeatureFlagCollaboration({ featureFlagId }: { featureFlagId: number }): JSX.Element | null {
    const {
        featureFlag,
        featureFlagLoading,
        canEditFeatureFlagAccess,
        canRestrictFeatureFlag,
    } = useValues(featureFlagLogic)
    const { saveFeatureFlag } = useActions(featureFlagLogic)
    const { allCollaborators, explicitCollaboratorsLoading, addableMembers, explicitCollaboratorsToBeAdded } =
        useValues(featureFlagCollaboratorsLogic({ featureFlagId }))
    const { deleteExplicitCollaborator, setExplicitCollaboratorsToBeAdded, addExplicitCollaborators } = useActions(
        featureFlagCollaboratorsLogic({ featureFlagId })
    )

    return (
        featureFlag && (
            <>
                <PayGateMini feature={AvailableFeature.FEATURE_FLAG_PERMISSIONING}>
                    {(!canEditFeatureFlagAccess || !canRestrictFeatureFlag) && (
                        <AlertMessage type="info">
                            {canEditFeatureFlagAccess
                                ? "You aren't allowed to change the restriction level – only the feature flag owner and project admins can."
                                : "You aren't allowed to change sharing settings – only feature flag collaborators with edit settings can."}
                        </AlertMessage>
                    )}
                    <LemonSelect
                        value={featureFlag.effective_restriction_level || FeatureFlagRestrictionLevel.EveryoneInProjectCanEdit}
                        onChange={(newValue) =>
                            saveFeatureFlag({
                                ...featureFlag,
                                restriction_level: newValue,
                            })
                        }
                        options={FEATURE_FLAG_RESTRICTION_OPTIONS}
                        loading={featureFlagLoading}
                        fullWidth
                        disabled={!canRestrictFeatureFlag}
                    />
                    {featureFlag.restriction_level > FeatureFlagRestrictionLevel.EveryoneInProjectCanEdit && (
                        <div className="mt-4">
                            <h5>Collaborators</h5>
                            {canEditFeatureFlagAccess && (
                                <div className="flex gap-2">
                                    <div className="flex-1">
                                        <LemonSelectMultiple
                                            placeholder="Search for team members to add…"
                                            value={explicitCollaboratorsToBeAdded}
                                            loading={explicitCollaboratorsLoading}
                                            onChange={(newValues) => setExplicitCollaboratorsToBeAdded(newValues)}
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
                            <div
                                className="mt-2 pb-2 rounded overflow-y-auto"
                                style={{
                                    maxHeight: 300,
                                }}
                            >
                                {allCollaborators.map((collaborator) => (
                                    <CollaboratorRow
                                        key={collaborator.user.uuid}
                                        collaborator={collaborator}
                                        deleteCollaborator={canEditFeatureFlagAccess ? deleteExplicitCollaborator : undefined}
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
    collaborator: FusedFeatureFlagCollaboratorType
    deleteCollaborator?: (userUuid: UserType['uuid']) => void
}): JSX.Element {
    const { user, level } = collaborator

    const wasInvited = level <= FeatureFlagPrivilegeLevel.CanEdit // Higher levels come from implicit privileges
    const privilegeLevelName = privilegeLevelToName[level]

    return (
        <div className="flex items-center justify-between mt-2 pl-2 h-8">
            <ProfilePicture email={user.email} name={user.first_name} size="md" showName />
            <Tooltip
                title={
                    !wasInvited
                        ? `${user.first_name || 'This person'} ${level === FeatureFlagPrivilegeLevel._Owner
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
                            icon={<IconDelete />}
                            onClick={() => deleteCollaborator(user.uuid)}
                            tooltip={wasInvited ? 'Remove invited collaborator' : null}
                            status="primary-alt"
                            type="tertiary"
                            size="small"
                        />
                    )}
                </div>
            </Tooltip>
        </div>
    )
}