import type { Meta, StoryObj } from '@storybook/react'

import * as rocket from '@posthog/brand/hoggies/png/rocket'
import { Button } from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'

import { DashboardV2Unavailable } from './DashboardV2Unavailable'

const HedgehogRocket = pngHoggie(rocket)

const meta: Meta<typeof DashboardV2Unavailable> = {
    title: 'Products/Dashboards v2/DashboardV2Unavailable',
    component: DashboardV2Unavailable,
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta

/** The default view for each problem. */
export const Defaults: StoryObj<typeof DashboardV2Unavailable> = {
    render: () => (
        <div className="grid grid-cols-2 gap-4">
            {(['notFound', 'noAccess'] as const).map((problem) => (
                <div key={problem} className="h-80">
                    <DashboardV2Unavailable problem={problem} />
                </div>
            ))}
        </div>
    ),
}

/** A product that replaces the words and hedgehog, and adds its own next step. */
export const Customized: StoryObj<typeof DashboardV2Unavailable> = {
    render: () => (
        <div className="h-80">
            <DashboardV2Unavailable
                problem="noAccess"
                illustration={<HedgehogRocket />}
                title="This service dashboard is private"
                description="Ask the service owner for access, or open the service list."
                actions={<Button variant="outline">Open services</Button>}
            />
        </div>
    ),
}
