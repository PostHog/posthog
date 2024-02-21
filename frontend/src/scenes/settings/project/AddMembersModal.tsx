import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonModal, LemonSelect, LemonSelectOption } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { RestrictedComponentProps } from 'lib/components/RestrictedArea'
import { usersLemonSelectOptions } from 'lib/components/UserSelectItem'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSelectMultiple } from 'lib/lemon-ui/LemonSelectMultiple/LemonSelectMultiple'
import { membershipLevelToName, teamMembershipLevelIntegers } from 'lib/utils/permissioning'
import { useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'

import { teamMembersLogic } from './teamMembersLogic'

export function AddMembersModalWithButton({ isRestricted }: RestrictedComponentProps): JSX.Element {
    const { addableMembers, allMembersLoading } = useValues(teamMembersLogic)
    const { currentTeam } = useValues(teamLogic)

    const [isVisible, setIsVisible] = useState(false)

    function closeModal(): void {
        setIsVisible(false)
    }

    return (
        <>
            <LemonButton
                type="primary"
                data-attr="add-project-members-button"
                onClick={() => {
                    setIsVisible(true)
                }}
                icon={<IconPlus />}
                disabled={isRestricted}
            >
                Add members to project
            </LemonButton>
            <LemonModal title="" onClose={closeModal} isOpen={isVisible} simple>
                <Form logic={teamMembersLogic} formKey="addMembers" enableFormOnSubmit>
                    <LemonModal.Header>
                        <h3>{`Adding members${currentTeam?.name ? ` to project ${currentTeam.name}` : ''}`}</h3>
                    </LemonModal.Header>
                    <LemonModal.Content className="space-y-2">
                        <LemonField name="userUuids">
                            <LemonSelectMultiple
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
                                        } as LemonSelectOption<TeamMembershipLevel>)
                                )}
                            />
                        </LemonField>
                    </LemonModal.Content>
                    <LemonModal.Footer>
                        <LemonButton type="secondary" onClick={closeModal}>
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
