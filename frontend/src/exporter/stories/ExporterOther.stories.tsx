import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { ExportType } from '~/exporter/types'

import { Exporter } from '../Exporter'

type Story = StoryObj<typeof Exporter>
const meta: Meta<typeof Exporter> = {
    title: 'Exporter/Other',
    component: Exporter,
    args: {
        type: ExportType.Embed,
        whitelabel: false,
        noHeader: false,
        legend: false,
        detailed: false,
    },
    parameters: {
        testOptions: {
            snapshotBrowsers: ['chromium'],
        },
        mockDate: '2023-02-01',
        viewMode: 'story',
    },
    tags: [], // Omit 'autodocs', as it's broken with Exporter
}

export default meta

const Template: StoryFn<typeof Exporter> = (props) => {
    useEffect(() => {
        document.body.className = ''
        document.documentElement.className = `export-type-${props.type}`
    }, [props.type])
    return (
        <div className={`storybook-export-type-${props.type} p-4`}>
            <Exporter {...props} />
        </div>
    )
}

export const RetentionInsight: Story = Template.bind({})
RetentionInsight.args = { insight: require('../../mocks/fixtures/api/projects/team_id/insights/retention.json') }

export const LifecycleInsight: Story = Template.bind({})
LifecycleInsight.args = { insight: require('../../mocks/fixtures/api/projects/team_id/insights/lifecycle.json') }
LifecycleInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const StickinessInsight: Story = Template.bind({})
StickinessInsight.args = { insight: require('../../mocks/fixtures/api/projects/team_id/insights/stickiness.json') }
StickinessInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const UserPathsInsight: Story = Template.bind({})
UserPathsInsight.args = { insight: require('../../mocks/fixtures/api/projects/team_id/insights/userPaths.json') }
UserPathsInsight.tags = ['test-skip'] // FIXME: flaky tests, most likely due to resize observer changes

export const EventTableInsight: Story = Template.bind({})
EventTableInsight.args = { insight: require('../../mocks/fixtures/api/projects/team_id/insights/dataTableEvents.json') }

/** This should not happen in the exporter, but if it does, it shouldn't error out - we want a clear message. */
export const EventTableInsightNoResults: Story = Template.bind({})
// @ts-expect-error
EventTableInsightNoResults.args = { insight: { ...EventTableInsight.args.insight, result: null } }

export const SQLInsight: Story = Template.bind({})
SQLInsight.args = { insight: require('../../mocks/fixtures/api/projects/team_id/insights/dataTableHogQL.json') }

/** This should not happen in the exporter, but if it does, it shouldn't error out - we want a clear message. */
export const SQLInsightNoResults: Story = Template.bind({})
// @ts-expect-error
SQLInsightNoResults.args = { insight: { ...SQLInsight.args.insight, result: null } }
