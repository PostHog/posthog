import { Meta, StoryObj } from '@storybook/react'

import { BreakdownTag as BreakdownTagComponent } from 'scenes/insights/filters/BreakdownFilter/BreakdownTag'

const meta: Meta<typeof BreakdownTagComponent> = {
    title: 'Filters/Breakdown Tag',
    component: BreakdownTagComponent,
    tags: ['autodocs'],
}

export default meta
type Story = StoryObj<typeof BreakdownTagComponent>

export const BreakdownTag: Story = {
    render: () => (
        <>
            <div className="mb-3">
                <h5>Basic breakdown tag</h5>
                <BreakdownTagComponent breakdownType="event" breakdown="$browser" onClick={() => alert('Clicked!')} />
            </div>
            <div className="mb-3">
                <h5>Breakdown tag for custom HogQL</h5>
                <BreakdownTagComponent
                    breakdownType="hogql"
                    breakdown="$properties.browser"
                    onClick={() => alert('Clicked!')}
                />
            </div>
            <div className="mb-3">
                <h5>Breakdown tag for custom HogQL, with title from comment</h5>
                <BreakdownTagComponent
                    breakdownType="hogql"
                    breakdown="coalesce(null, 1, 2) -- some sql"
                    onClick={() => alert('Clicked!')}
                />
            </div>
            <div className="mb-3">
                <h5>Breakdown tag for cohort</h5>
                <BreakdownTagComponent breakdownType="cohort" breakdown={1} onClick={() => alert('Clicked!')} />
            </div>
            <div className="mb-3">
                <h5>Breakdown tag with close button</h5>
                <BreakdownTagComponent
                    breakdownType="event"
                    breakdown="$browser"
                    onClose={() => alert('Closed!')}
                    onClick={() => alert('Clicked!')}
                />
            </div>
            <div className="mb-3">
                <h5>Breakdown tag with small size</h5>
                <BreakdownTagComponent
                    breakdownType="event"
                    breakdown="$browser"
                    size="small"
                    onClick={() => alert('Clicked!')}
                />
            </div>
            <div className="mb-3">
                <h5>Breakdown tag with small size and close button</h5>
                <BreakdownTagComponent
                    breakdownType="event"
                    breakdown="$browser"
                    size="small"
                    onClose={() => alert('Closed!')}
                    onClick={() => alert('Clicked!')}
                />
            </div>
            <div className="mb-3">
                <h5>Breakdown tag without click handler</h5>
                <BreakdownTagComponent breakdownType="event" breakdown="$browser" />
            </div>
            <div className="mb-3">
                <h5>Breakdown tag with disabled property info</h5>
                <BreakdownTagComponent
                    breakdownType="event"
                    breakdown="$browser"
                    disablePropertyInfo
                    onClick={() => alert('Clicked!')}
                />
            </div>
            <div className="mb-3">
                <h5>Breakdown tag with popover</h5>
                <BreakdownTagComponent
                    breakdownType="event"
                    breakdown="$browser"
                    popover={{
                        overlay: <div>Popover</div>,
                        closeOnClickInside: false,
                    }}
                    onClick={() => alert('Clicked!')}
                />
            </div>
        </>
    ),
}
