import type { Meta, StoryObj } from '@storybook/react'

import { ListScopeChip } from './ListScopeChip'

const meta: Meta<typeof ListScopeChip> = {
    title: 'Scenes-App/AI observability/Lists/List scope chip',
    component: ListScopeChip,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { onClear: () => {} },
}
export default meta

type Story = StoryObj<typeof ListScopeChip>

const LONG_ERROR =
    'Request failed with status 429: rate limit reached for requests per minute on the default organization. Retry after 20 seconds.'

export const EveryKindInANarrowContainer: Story = {
    render: (args) => (
        <div className="flex w-80 flex-wrap items-center gap-2">
            <ListScopeChip
                {...args}
                scope={{ kind: 'person', value: '0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b' }}
                label="2e3f4a5b"
            />
            <ListScopeChip {...args} scope={{ kind: 'error', value: LONG_ERROR }} label={LONG_ERROR} />
            <ListScopeChip {...args} scope={{ kind: 'tool', value: 'search_docs' }} label="search_docs" />
        </div>
    ),
}
