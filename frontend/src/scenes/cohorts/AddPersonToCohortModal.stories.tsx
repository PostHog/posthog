import { Meta, StoryFn } from '@storybook/react'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonModal, LemonTag } from '@posthog/lemon-ui'

import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import './AddPersonToCohortModalBody.scss'

const meta: Meta = {
    title: 'Scenes-App/People/Cohorts/Add Person To Cohort Modal',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2023-07-04',
    },
}
export default meta

const mockPersons = [
    { id: '017cf78e-a849-0000-0000-01fe9b8d7233', display_name: 'Jane Doe', isInCohort: true, isAdded: false },
    { id: '01804f4e-0fb7-0000-0000-0db0398f4d98', display_name: 'John Smith', isInCohort: false, isAdded: true },
    {
        id: '0188f346-0564-0000-0000-16bc74aebc20',
        display_name: 'alice@example.com',
        isInCohort: false,
        isAdded: false,
    },
    { id: '0184f5e9-bb76-0000-0000-2ac415274e4a', display_name: 'Bob Wilson', isInCohort: false, isAdded: true },
    { id: '017fc2b7-d6f0-0000-0000-31f9a1f40e06', display_name: 'charlie@test.com', isInCohort: true, isAdded: false },
]

function PersonRow({ person }: { person: (typeof mockPersons)[0] }): JSX.Element {
    return (
        <div className="AddPersonToCohortModalBody__row" style={{ height: 44 }}>
            <LemonCheckbox
                checked={person.isInCohort || person.isAdded}
                disabled={person.isInCohort}
                onChange={() => {}}
                data-attr="cohort-person-checkbox"
            />
            <div className="flex items-center justify-between flex-1 gap-2 min-w-0">
                <div className="flex items-center gap-2 min-w-0">
                    <PersonDisplay
                        person={{ id: person.id }}
                        displayName={person.display_name}
                        withIcon
                        noLink
                        noPopover
                    />
                    {person.isInCohort && <LemonTag type="success">In cohort</LemonTag>}
                </div>
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={<IconExternal />}
                    tooltip="Open person in new tab"
                    data-attr="cohort-person-open-in-new-tab"
                />
            </div>
        </div>
    )
}

export const ModalInline: StoryFn = () => {
    return (
        <div className="bg-default p-4">
            <LemonModal
                isOpen={false}
                onClose={() => {}}
                title="Add users to cohort"
                inline
                footer={
                    <div className="flex items-center justify-end gap-2">
                        <LemonButton type="secondary" data-attr="cohort-add-users-modal-cancel">
                            Cancel
                        </LemonButton>
                        <LemonButton type="primary" data-attr="cohort-add-users-modal-save">
                            Save
                        </LemonButton>
                    </div>
                }
            >
                <div className="AddPersonToCohortModalBody">
                    <LemonInput type="search" placeholder="Search by name, email, Person ID or Distinct ID" fullWidth />
                    <div className="flex flex-col">
                        {mockPersons.map((person) => (
                            <PersonRow key={person.id} person={person} />
                        ))}
                    </div>
                </div>
            </LemonModal>
        </div>
    )
}

export const ModalWithAllSelected: StoryFn = () => {
    return (
        <div className="bg-default p-4">
            <LemonModal
                isOpen={false}
                onClose={() => {}}
                title="Add users to cohort"
                inline
                footer={
                    <div className="flex items-center justify-end gap-2">
                        <LemonButton type="secondary" data-attr="cohort-add-users-modal-cancel">
                            Cancel
                        </LemonButton>
                        <LemonButton type="primary" data-attr="cohort-add-users-modal-save">
                            Save
                        </LemonButton>
                    </div>
                }
            >
                <div className="AddPersonToCohortModalBody">
                    <LemonInput type="search" placeholder="Search by name, email, Person ID or Distinct ID" fullWidth />
                    <div className="flex flex-col">
                        {mockPersons.map((person) => (
                            <PersonRow key={person.id} person={{ ...person, isAdded: true }} />
                        ))}
                    </div>
                </div>
            </LemonModal>
        </div>
    )
}

export const ModalEmpty: StoryFn = () => {
    return (
        <div className="bg-default p-4">
            <LemonModal
                isOpen={false}
                onClose={() => {}}
                title="Add users to cohort"
                inline
                footer={
                    <div className="flex items-center justify-end gap-2">
                        <LemonButton type="secondary" data-attr="cohort-add-users-modal-cancel">
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            disabledReason="Select at least one user"
                            data-attr="cohort-add-users-modal-save"
                        >
                            Save
                        </LemonButton>
                    </div>
                }
            >
                <div className="AddPersonToCohortModalBody">
                    <LemonInput type="search" placeholder="Search by name, email, Person ID or Distinct ID" fullWidth />
                    <div className="flex items-center justify-center py-8 text-muted">
                        Search for persons to add to this cohort.
                    </div>
                </div>
            </LemonModal>
        </div>
    )
}
