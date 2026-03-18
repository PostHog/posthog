import { Meta, StoryFn } from '@storybook/react'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { useStorybookMocks } from '~/mocks/browser'
import { NodeKind } from '~/queries/schema/schema-general'

import { PersonSelectList } from './PersonSelectList'

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
    { id: '017cf78e-a849-0000-0000-01fe9b8d7233', display_name: 'Jane Doe' },
    { id: '01804f4e-0fb7-0000-0000-0db0398f4d98', display_name: 'John Smith' },
    { id: '0188f346-0564-0000-0000-16bc74aebc20', display_name: 'alice@example.com' },
    { id: '0184f5e9-bb76-0000-0000-2ac415274e4a', display_name: 'Bob Wilson' },
    { id: '017fc2b7-d6f0-0000-0000-31f9a1f40e06', display_name: 'charlie@test.com' },
]

const mockQueryResponse = {
    columns: ['id', 'person_display_name -- Person'],
    results: mockPersons.map((p) => [p.id, p]),
    hasMore: false,
    is_cached: true,
    cache_key: 'test-persons',
    calculation_trigger: null,
    error: '',
    query_status: null,
}

const DEFAULT_QUERY = {
    kind: NodeKind.ActorsQuery as const,
    fixedProperties: [],
    select: ['id', 'person_display_name -- Person'],
}

const noop = (): void => {}

function ModalShell({
    children,
    saveDisabledReason,
}: {
    children: React.ReactNode
    saveDisabledReason?: string
}): JSX.Element {
    return (
        <div className="bg-default p-4">
            <LemonModal
                isOpen={false}
                onClose={noop}
                title="Add users to cohort"
                inline
                footer={
                    <div className="flex items-center justify-end gap-2">
                        <LemonButton type="secondary" data-attr="cohort-add-users-modal-cancel">
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            disabledReason={saveDisabledReason}
                            data-attr="cohort-add-users-modal-save"
                        >
                            Save
                        </LemonButton>
                    </div>
                }
            >
                {children}
            </LemonModal>
        </div>
    )
}

export const ModalInline: StoryFn = () => {
    useStorybookMocks({
        post: { '/api/environments/:team_id/query/': mockQueryResponse },
    })

    return (
        <ModalShell>
            <PersonSelectList
                query={DEFAULT_QUERY}
                setQuery={noop}
                selectedPersons={{
                    [mockPersons[1].id]: true,
                    [mockPersons[3].id]: true,
                }}
                onAddPerson={noop}
                onRemovePerson={noop}
                existingPersonsSet={new Set([mockPersons[0].id, mockPersons[4].id])}
                dataNodeKey="story-modal-inline"
            />
        </ModalShell>
    )
}

export const ModalWithAllSelected: StoryFn = () => {
    useStorybookMocks({
        post: { '/api/environments/:team_id/query/': mockQueryResponse },
    })

    const allSelected = Object.fromEntries(mockPersons.map((p) => [p.id, true]))

    return (
        <ModalShell>
            <PersonSelectList
                query={DEFAULT_QUERY}
                setQuery={noop}
                selectedPersons={allSelected}
                onAddPerson={noop}
                onRemovePerson={noop}
                dataNodeKey="story-modal-all-selected"
            />
        </ModalShell>
    )
}

export const ModalEmpty: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/query/': {
                ...mockQueryResponse,
                results: [],
            },
        },
    })

    return (
        <ModalShell saveDisabledReason="Select at least one user">
            <PersonSelectList
                query={DEFAULT_QUERY}
                setQuery={noop}
                selectedPersons={{}}
                onAddPerson={noop}
                onRemovePerson={noop}
                dataNodeKey="story-modal-empty"
            />
        </ModalShell>
    )
}
