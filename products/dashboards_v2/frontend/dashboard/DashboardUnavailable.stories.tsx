import type { Meta, StoryObj } from '@storybook/react'

import * as rocket from '@posthog/brand/hoggies/png/rocket'
import { Button } from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'

import { DashboardUnavailable } from './DashboardUnavailable'

const HedgehogRocket = pngHoggie(rocket)

const meta: Meta<typeof DashboardUnavailable> = {
    title: 'Products/Dashboards v2/DashboardUnavailable',
    component: DashboardUnavailable,
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta

export const Defaults: StoryObj<typeof DashboardUnavailable> = {
    render: () => (
        <div className="grid grid-cols-2 gap-4">
            {(['notFound', 'noAccess'] as const).map((problem) => (
                <div key={problem} className="h-80">
                    <DashboardUnavailable problem={problem} />
                </div>
            ))}
        </div>
    ),
}

/** A product that replaces the words and hedgehog, and adds its own next step. */
export const Customized: StoryObj<typeof DashboardUnavailable> = {
    render: () => (
        <div className="h-80">
            <DashboardUnavailable
                problem="noAccess"
                illustration={<HedgehogRocket />}
                title="This service dashboard is private"
                description="Ask the service owner for access, or open the service list."
                actions={<Button variant="outline">Open services</Button>}
            />
        </div>
    ),
}
