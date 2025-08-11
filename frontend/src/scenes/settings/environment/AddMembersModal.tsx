import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonModal, LemonSelect, LemonSelectOption } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { usersLemonSelectOptions } from 'lib/components/UserSelectItem'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { membershipLevelToName, teamMembershipLevelIntegers } from 'lib/utils/permissioning'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import { teamMembersLogic } from './teamMembersLogic'

export function AddMembersModalWithButton({ disabledReason }: { disabledReason: string | null }): JSX.Element {
    const { addableMembers, allMembersLoading, isAddMembersModalOpen } = useValues(teamMembersLogic)
    const { openAddMembersModal, closeAddMembersModal } = useActions(teamMembersLogic)
    const { currentTeam } = useValues(teamLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { hasAvailableFeature } = useValues(userLogic)

    return (
        <>
            <LemonButton
                type="primary"
                data-attr="add-project-members-button"
                onClick={() =>
                    guardAvailableFeature(AvailableFeature.ADVANCED_PERMISSIONS, () => openAddMembersModal(), {
                        isGrandfathered:
                            !hasAvailableFeature(AvailableFeature.ADVANCED_PERMISSIONS) && currentTeam?.access_control,
                    })
                }
                icon={<IconPlus />}
                disabledReason={disabledReason}
            >
                Add members to project
            </LemonButton>
            <LemonModal title="" onClose={closeAddMembersModal} isOpen={isAddMembersModalOpen} simple>
                <Form logic={teamMembersLogic} formKey="addMembers" enableFormOnSubmit>
                    <LemonModal.Header>
                        <h3>{`Adding members${currentTeam?.name ? ` to project ${currentTeam.name}` : ''}`}</h3>
                    </LemonModal.Header>
                    <LemonModal.Content className="deprecated-space-y-2">
                        <LemonField name="userUuids">
                            <LemonInputSelect
                                mode="multiple"
                                placeholder="Organization members"
                                loading={allMembersLoading}
                                options={usersLemonSelectOptions(
                                    addableMembers.map((x) => x.user),
                                    'uuid'
                                )}
                            />
                        </LemonField>
                        <LemonField name="level" label="With project-specific access level">
                            <LemonSelect
                                fullWidth
                                options={teamMembershipLevelIntegers.map(
                                    (teamMembershipLevel) =>
                                        ({
                                            value: teamMembershipLevel,
                                            label: membershipLevelToName.get(teamMembershipLevel),
                                        }) as LemonSelectOption<TeamMembershipLevel>
                                )}
                            />
                        </LemonField>
                    </LemonModal.Content>
                    <LemonModal.Footer>
                        <LemonButton type="secondary" onClick={closeAddMembersModal}>
                            Cancel
                        </LemonButton>
                        <LemonButton type="primary" data-attr="add-project-members-submit" htmlType="submit">
                            Add members to project
                        </LemonButton>
                    </LemonModal.Footer>
                </Form>
            </LemonModal>
        </>
    )
}
