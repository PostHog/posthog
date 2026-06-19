import type { Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { urls } from 'scenes/urls'

import { useStorybookMocks } from '~/mocks/browser'
import { LLMTrace } from '~/queries/schema/schema-general'

import fullTrace from './__mocks__/fullTrace.json'
import traceWithoutContent from './__mocks__/traceWithoutContent.json'
import { AIObservabilityTraceScene } from './AIObservabilityTraceScene'

interface AIObservabilityTraceSceneProps {
    trace: LLMTrace
    eventId?: string
}

const getEffectiveQueryKind = (req: {
    body?: { query?: { kind?: string; source?: { kind?: string } } }
}): string | undefined => req.body?.query?.source?.kind ?? req.body?.query?.kind

const meta: Meta<AIObservabilityTraceSceneProps> = {
    title: 'Scenes-App/AI observability/Trace',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
    },
    render: ({ trace, eventId }) => {
        useStorybookMocks({
            post: {
                '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                    const body = (await request.json()) as {
                        query?: { kind?: string; source?: { kind?: string } }
                    }
                    if (getEffectiveQueryKind({ body }) === 'TraceQuery') {
                        return [200, { results: [trace] }]
                    }
                },
            },
        })

        useOnMountEffect(() => {
            router.actions.push(
                urls.aiObservabilityTrace(
                    trace.id,
                    eventId ? { event: eventId, timestamp: trace.createdAt } : undefined
                )
            )
        })

        return (
            <div className="relative flex flex-col p-4">
                <AIObservabilityTraceScene />
            </div>
        )
    },
}
export default meta
type Story = StoryObj<AIObservabilityTraceSceneProps>

export const Full: Story = {
    args: {
        trace: fullTrace,
    },
}

export const FullSpecificEvent: Story = {
    args: {
        trace: fullTrace,
        eventId: fullTrace.events.at(-8)!.id,
    },
}

export const WithoutContent: Story = {
    args: {
        trace: traceWithoutContent,
    },
}
