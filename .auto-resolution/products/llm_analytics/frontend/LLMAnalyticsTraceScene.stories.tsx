import { Meta, StoryFn } from '@storybook/react'
import { router } from 'kea-router'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { urls } from 'scenes/urls'

import { useStorybookMocks } from '~/mocks/browser'
import { LLMTrace } from '~/queries/schema/schema-general'

import { LLMAnalyticsTraceScene } from './LLMAnalyticsTraceScene'
import fullTrace from './__mocks__/fullTrace.json'

const meta: Meta = {
    title: 'Scenes-App/LLM Analytics/Trace',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
    },
}
export default meta

const Template: StoryFn<{ trace: LLMTrace; eventId?: string }> = ({ trace, eventId }) => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/query/': () => [200, { results: [trace] }],
        },
    })

    useOnMountEffect(() => {
        router.actions.push(
            urls.llmAnalyticsTrace(trace.id, eventId ? { event: eventId, timestamp: trace.createdAt } : undefined)
        )
    })

    return (
        <div className="relative flex flex-col p-4">
            <LLMAnalyticsTraceScene />
        </div>
    )
}

export const Full = Template.bind({})
Full.args = {
    trace: fullTrace,
}

export const FullSpecificEvent = Template.bind({})
FullSpecificEvent.args = {
    trace: fullTrace,
    eventId: fullTrace.events.at(-8)!.id,
}
