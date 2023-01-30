import { useState } from 'react'
import { useValues } from 'kea'
import { teamMembersLogic } from './teamMembersLogic'
import { teamLogic } from 'scenes/teamLogic'
import { membershipLevelToName, teamMembershipLevelIntegers } from 'lib/utils/permissioning'
import { RestrictedComponentProps } from 'lib/components/RestrictedArea'
import { LemonButton, LemonModal, LemonSelect, LemonSelectOption } from '@posthog/lemon-ui'
import { LemonSelectMultiple } from 'lib/lemon-ui/LemonSelectMultiple/LemonSelectMultiple'
import { usersLemonSelectOptions } from 'lib/components/UserSelectItem'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { IconPlus } from 'lib/lemon-ui/icons'
import { TeamMembershipLevel } from 'lib/constants'

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
            <LemonModal title={''} onClose={closeModal} isOpen={isVisible} simple>
                <Form logic={teamMembersLogic} formKey={'addMembers'} enableFormOnSubmit>
                    <LemonModal.Header>
                        <h3>{`Adding members${currentTeam?.name ? ` to project ${currentTeam.name}` : ''}`}</h3>
                    </LemonModal.Header>
                    <LemonModal.Content className="space-y-2">
                        <Field name="userUuids">
                            <LemonSelectMultiple
                                mode="multiple"
                                placeholder="Organization members"
                                loading={allMembersLoading}
                                options={usersLemonSelectOptions(
                                    addableMembers.map((x) => x.user),
                                    'uuid'
                                )}
                            />
                        </Field>
                        <Field name="level" label="With project-specific access level">
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
                        </Field>
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
