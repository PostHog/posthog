import type { Meta, StoryObj } from '@storybook/react'

import { LemonTable } from 'lib/lemon-ui/LemonTable'

import type { PersonListItemApi } from '../../../generated/api.schemas'
import { makePersonListItem } from '../testFixtures'
import { peopleTableColumns } from './PeopleTableColumns'

const ITEMS: PersonListItemApi[] = [
    makePersonListItem({
        id: 'person-1',
        person: { distinctId: 'ana@example.com', label: 'Ana Example' },
        traceCount: 1240,
        sessionCount: 88,
        cost: 12.5,
    }),
    makePersonListItem({
        id: 'person-2',
        person: {
            distinctId: 'a.very.long.address.for.truncation@example.com',
            label: 'a.very.long.address.for.truncation@example.com',
        },
        sessionCount: 0,
        cost: null,
    }),
    makePersonListItem({
        id: 'person-3',
        person: { distinctId: '0192f3c9-a1d2-7b4e-9c8f-5e6d7a8b9c0d', label: 'Anonymous 0192f3c9' },
        anonymous: true,
        cost: 0.0004,
    }),
]

function PeopleTable(): JSX.Element {
    return (
        <LemonTable
            columns={peopleTableColumns()}
            dataSource={ITEMS}
            rowKey={(item) => item.id}
            useURLForSorting={false}
        />
    )
}

const meta: Meta<typeof PeopleTable> = {
    title: 'Scenes-App/AI observability/People/People table columns',
    component: PeopleTable,
    parameters: { mockDate: '2026-11-25', testOptions: { snapshotBrowsers: [] } },
    decorators: [
        (StoryComponent) => (
            <div className="w-120">
                <StoryComponent />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof PeopleTable>

export const NarrowContainer: Story = {}
