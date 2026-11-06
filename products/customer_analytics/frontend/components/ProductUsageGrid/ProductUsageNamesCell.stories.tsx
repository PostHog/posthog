import type { Meta, StoryObj } from '@storybook/react'

import { ProductUsageNamesCell } from './ProductUsageNamesCell'
const people = ['Ana', 'Bo', 'Cy'].map((name, index) => ({
    row: 'example-account',
    column: '2026-10-05',
    series: 'analytics',
    personId: `person-${index}`,
    label: `${name.toLowerCase()}@example.com`,
    rank: index + 1,
    engagedSeconds: 120 - index * 20,
    actionCount: 3 - index,
    actions: [{ event: 'report opened', count: 3 - index }],
    topPaths: [{ path: '/reports', seconds: 120 - index * 20 }],
}))
const meta: Meta<typeof ProductUsageNamesCell> = {
    title: 'Customer Analytics/Product activity/Names',
    component: ProductUsageNamesCell,
    args: {
        people,
        total: 5,
        columnKey: '2026-10-05',
        interval: 'week',
        expanded: false,
        firstUse: [
            {
                row: 'example-account',
                series: 'analytics',
                personId: 'person-0',
                label: 'ana@example.com',
                date: '2026-10-07',
            },
        ],
        onToggle: () => undefined,
    },
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta
export const NamesWithFirstUse: StoryObj<typeof meta> = {}
