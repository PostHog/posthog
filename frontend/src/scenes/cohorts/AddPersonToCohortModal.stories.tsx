import { Meta, StoryFn } from '@storybook/react'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonModal, LemonTag } from '@posthog/lemon-ui'

import { PersonDisplay } from 'scenes/persons/PersonDisplay'

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
    {
        id: '017cf78e-a849-0000-0000-01fe9b8d7233',
        distinct_id: 'user-1',
        display_name: 'Jane Doe',
        isInCohort: true,
        isAdded: false,
    },
    {
        id: '01804f4e-0fb7-0000-0000-0db0398f4d98',
        distinct_id: 'user-2',
        display_name: 'John Smith',
        isInCohort: false,
        isAdded: true,
    },
    {
        id: '0188f346-0564-0000-0000-16bc74aebc20',
        distinct_id: 'user-3',
        display_name: 'alice@example.com',
        isInCohort: false,
        isAdded: false,
    },
    {
        id: '0184f5e9-bb76-0000-0000-2ac415274e4a',
        distinct_id: 'user-4',
        display_name: 'Bob Wilson',
        isInCohort: false,
        isAdded: true,
    },
    {
        id: '017fc2b7-d6f0-0000-0000-31f9a1f40e06',
        distinct_id: 'user-5',
        display_name: 'charlie@test.com',
        isInCohort: true,
        isAdded: false,
    },
]

function PersonRow({
    person,
}: {
    person: (typeof mockPersons)[0]
}): JSX.Element {
    const isChecked = person.isInCohort || person.isAdded

    return (
        <div className="flex items-center gap-3 px-3 py-2 rounded hover:bg-[var(--color-bg-light)]">
            <LemonCheckbox
                checked={isChecked}
                disabled={person.isInCohort}
                onChange={() => {}}
                data-attr="cohort-person-checkbox"
            />
            <div className="flex items-center justify-between w-full gap-2">
                <div className="flex items-center gap-2 min-w-0">
                    <PersonDisplay
                        person={{ id: person.id, distinct_id: person.distinct_id }}
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
                <div className="min-w-180 AddPersonToCohortModalBody">
                    <div className="flex flex-col gap-0">
                        {mockPersons.map((person) => (
                            <PersonRow key={person.id} person={person} />
                        ))}
                    </div>
                </div>
            </LemonModal>
        </div>
    )
}

export const ModalWithSelectedPersons: StoryFn = () => {
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
                <div className="min-w-180 AddPersonToCohortModalBody">
                    <div className="flex flex-col gap-0">
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
                <div className="min-w-180 AddPersonToCohortModalBody">
                    <div className="flex flex-col items-center justify-center py-8 text-muted">
                        Search for persons to add to this cohort.
                    </div>
                </div>
            </LemonModal>
        </div>
    )
}
