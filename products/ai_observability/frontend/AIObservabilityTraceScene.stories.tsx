import type { Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { LLMTrace } from '~/queries/schema/schema-general'

import fullTrace from './__mocks__/fullTrace.json'
import traceWithoutContent from './__mocks__/traceWithoutContent.json'
import { AIObservabilityTraceScene } from './AIObservabilityTraceScene'
import { AIObservabilityInstrumentationCheckEnumApi, InstrumentationCheckStatusEnumApi } from './generated/api.schemas'

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

export const MissingSpanInstrumentation: Story = {
    args: {
        trace: traceWithoutContent,
    },
    parameters: {
        featureFlags: [FEATURE_FLAGS.AI_OBSERVABILITY_INSTRUMENTATION_CHECKLIST],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/ai_observability/instrumentation_checklist/': {
                    window_days: 30,
                    checks: [
                        {
                            key: AIObservabilityInstrumentationCheckEnumApi.TraceStructure,
                            status: InstrumentationCheckStatusEnumApi.Warning,
                            title: 'Trace structure',
                            detail: 'Without spans, a trace shows LLM calls but not the retrieval, chains or sub-agent steps around them.',
                            docs_url: 'https://posthog.com/docs/ai-observability/installation',
                            stats: { total_events: 1611, spans: 0, events_with_parent: 0 },
                        },
                    ],
                },
            },
        }),
    ],
}
