import type { Meta, StoryObj } from '@storybook/react'

import { LemonTable } from 'lib/lemon-ui/LemonTable'

import type { PersonListItemApi } from '../../../generated/api.schemas'
import type { CellLoads, TraceCellLoad } from '../../shared/cellLoads'
import { ready } from '../../traces/testFixtures'
import { makePersonListItem } from '../testFixtures'
import type { PersonFirstSeen } from '../types'
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

const FIRST_SEEN: CellLoads<PersonFirstSeen> = new Map<string, TraceCellLoad<PersonFirstSeen>>([
    ['person-1', ready({ firstSeen: '2026-11-20T09:15:00Z', checkedFrom: '2026-10-18', isNew: true })],
    ['person-2', ready({ firstSeen: null, checkedFrom: '2026-10-18', isNew: true })],
    ['person-3', { status: 'error' }],
])

function PeopleTable({ firstSeen }: { firstSeen: CellLoads<PersonFirstSeen> }): JSX.Element {
    return (
        <LemonTable
            columns={peopleTableColumns({ firstSeen })}
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
    args: { firstSeen: FIRST_SEEN },
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

export const FirstSeenLoading: Story = { args: { firstSeen: new Map() } }
