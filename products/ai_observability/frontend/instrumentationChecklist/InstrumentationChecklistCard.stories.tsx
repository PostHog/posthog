import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import {
    AIObservabilityInstrumentationCheckEnumApi,
    InstrumentationCheckApi,
    InstrumentationCheckStatusEnumApi,
    InstrumentationChecklistApi,
} from '../generated/api.schemas'
import { InstrumentationChecklistCard } from './InstrumentationChecklistCard'

// Every title, detail and docs URL below is copied from the grader that produces them,
// products/ai_observability/backend/instrumentation_checklist/grading.py. These stories are the
// card's visual-regression baseline, so copy invented here would get approved as the way the card
// looks even though the API never sends it.
const INSTALLATION_DOCS_URL = 'https://posthog.com/docs/ai-observability/installation'
const SESSIONS_DOCS_URL = 'https://posthog.com/docs/ai-observability/sessions'
const TOOLS_DOCS_URL = 'https://posthog.com/docs/ai-observability/tools'

const SESSIONS: Record<InstrumentationCheckStatusEnumApi, InstrumentationCheckApi> = {
    ok: {
        key: AIObservabilityInstrumentationCheckEnumApi.Sessions,
        status: InstrumentationCheckStatusEnumApi.Ok,
        title: 'Sessions',
        detail: 'Traces are grouping into sessions.',
        docs_url: SESSIONS_DOCS_URL,
        stats: { generations: 1284, events_with_session: 842, events_declining_session: 0 },
    },
    warning: {
        key: AIObservabilityInstrumentationCheckEnumApi.Sessions,
        status: InstrumentationCheckStatusEnumApi.Warning,
        title: 'Sessions',
        detail: 'No traces include $ai_session_id. If your product has multi-turn conversations, setting it lets us group them into sessions. Workloads that are complete in one trace, like batch jobs or one-shot generation, do not need it. Send $ai_session_id as null on those to say so.',
        docs_url: SESSIONS_DOCS_URL,
        stats: { generations: 1284, events_with_session: 0, events_declining_session: 0 },
    },
    pending: {
        key: AIObservabilityInstrumentationCheckEnumApi.Sessions,
        status: InstrumentationCheckStatusEnumApi.Pending,
        title: 'Sessions',
        detail: 'Still collecting data. This check runs once there are 20 generations.',
        docs_url: SESSIONS_DOCS_URL,
        stats: { generations: 4, events_with_session: 0, events_declining_session: 0 },
    },
    dismissed: {
        key: AIObservabilityInstrumentationCheckEnumApi.Sessions,
        status: InstrumentationCheckStatusEnumApi.Dismissed,
        title: 'Sessions',
        detail: 'No traces include $ai_session_id. If your product has multi-turn conversations, setting it lets us group them into sessions. Workloads that are complete in one trace, like batch jobs or one-shot generation, do not need it. Send $ai_session_id as null on those to say so.',
        docs_url: SESSIONS_DOCS_URL,
        stats: { generations: 1284, events_with_session: 0, events_declining_session: 0 },
    },
}

const TOOL_CALLS: Record<InstrumentationCheckStatusEnumApi, InstrumentationCheckApi> = {
    ok: {
        key: AIObservabilityInstrumentationCheckEnumApi.ToolCalls,
        status: InstrumentationCheckStatusEnumApi.Ok,
        title: 'Tool calls',
        detail: 'Tool calls are being recorded.',
        docs_url: TOOLS_DOCS_URL,
        stats: { generations: 1284, generations_with_tool_calls: 310, generations_with_tools_declared: 640 },
    },
    warning: {
        key: AIObservabilityInstrumentationCheckEnumApi.ToolCalls,
        status: InstrumentationCheckStatusEnumApi.Warning,
        title: 'Tool calls',
        detail: 'No tool calls recorded, but you are sending tool definitions. If your agent does call tools, check that your SDK version reports them.',
        docs_url: TOOLS_DOCS_URL,
        stats: { generations: 1284, generations_with_tool_calls: 0, generations_with_tools_declared: 640 },
    },
    pending: {
        key: AIObservabilityInstrumentationCheckEnumApi.ToolCalls,
        status: InstrumentationCheckStatusEnumApi.Pending,
        title: 'Tool calls',
        detail: 'Still collecting data. This check runs once there are 20 generations.',
        docs_url: TOOLS_DOCS_URL,
        stats: { generations: 4, generations_with_tool_calls: 0, generations_with_tools_declared: 0 },
    },
    dismissed: {
        key: AIObservabilityInstrumentationCheckEnumApi.ToolCalls,
        status: InstrumentationCheckStatusEnumApi.Dismissed,
        title: 'Tool calls',
        detail: 'No tool calls recorded. If your app uses tool or function calling, capture it to see which tools run and how often.',
        docs_url: TOOLS_DOCS_URL,
        stats: { generations: 1284, generations_with_tool_calls: 0, generations_with_tools_declared: 0 },
    },
}

const USER_IDENTITY: Record<InstrumentationCheckStatusEnumApi, InstrumentationCheckApi> = {
    ok: {
        key: AIObservabilityInstrumentationCheckEnumApi.UserIdentity,
        status: InstrumentationCheckStatusEnumApi.Ok,
        title: 'User identity',
        detail: 'AI events are attributed to identified users.',
        docs_url: INSTALLATION_DOCS_URL,
        stats: { sdk_generations: 1284, sdk_generations_identified: 1284 },
    },
    warning: {
        key: AIObservabilityInstrumentationCheckEnumApi.UserIdentity,
        status: InstrumentationCheckStatusEnumApi.Warning,
        title: 'User identity',
        detail: 'Generations are arriving with their trace ID as the distinct ID, so usage and cost cannot be tied to people. Set distinct_id to your own user identifier.',
        docs_url: INSTALLATION_DOCS_URL,
        stats: { sdk_generations: 1284, sdk_generations_identified: 0 },
    },
    pending: {
        key: AIObservabilityInstrumentationCheckEnumApi.UserIdentity,
        status: InstrumentationCheckStatusEnumApi.Pending,
        title: 'User identity',
        detail: 'This check runs once there are 20 generations from a PostHog SDK. Generations sent over OpenTelemetry are not counted, because we cannot tell whether they are identified.',
        docs_url: INSTALLATION_DOCS_URL,
        stats: { sdk_generations: 4, sdk_generations_identified: 0 },
    },
    dismissed: {
        key: AIObservabilityInstrumentationCheckEnumApi.UserIdentity,
        status: InstrumentationCheckStatusEnumApi.Dismissed,
        title: 'User identity',
        detail: 'Generations are arriving with their trace ID as the distinct ID, so usage and cost cannot be tied to people. Set distinct_id to your own user identifier.',
        docs_url: INSTALLATION_DOCS_URL,
        stats: { sdk_generations: 1284, sdk_generations_identified: 0 },
    },
}

const TRACE_STRUCTURE: Record<InstrumentationCheckStatusEnumApi, InstrumentationCheckApi> = {
    ok: {
        key: AIObservabilityInstrumentationCheckEnumApi.TraceStructure,
        status: InstrumentationCheckStatusEnumApi.Ok,
        title: 'Trace structure',
        detail: 'Traces show the steps around your LLM calls.',
        docs_url: INSTALLATION_DOCS_URL,
        stats: { total_events: 1611, spans: 327, events_with_parent: 327 },
    },
    warning: {
        key: AIObservabilityInstrumentationCheckEnumApi.TraceStructure,
        status: InstrumentationCheckStatusEnumApi.Warning,
        title: 'Trace structure',
        detail: 'Without spans, a trace shows LLM calls but not the retrieval, chains or sub-agent steps around them.',
        docs_url: INSTALLATION_DOCS_URL,
        stats: { total_events: 1611, spans: 0, events_with_parent: 0 },
    },
    pending: {
        key: AIObservabilityInstrumentationCheckEnumApi.TraceStructure,
        status: InstrumentationCheckStatusEnumApi.Pending,
        title: 'Trace structure',
        detail: 'Still collecting data. This check runs once there are 20 AI events.',
        docs_url: INSTALLATION_DOCS_URL,
        stats: { total_events: 6, spans: 0, events_with_parent: 0 },
    },
    dismissed: {
        key: AIObservabilityInstrumentationCheckEnumApi.TraceStructure,
        status: InstrumentationCheckStatusEnumApi.Dismissed,
        title: 'Trace structure',
        detail: 'Without spans, a trace shows LLM calls but not the retrieval, chains or sub-agent steps around them.',
        docs_url: INSTALLATION_DOCS_URL,
        stats: { total_events: 1611, spans: 0, events_with_parent: 0 },
    },
}

function checklist(
    sessions: InstrumentationCheckStatusEnumApi,
    toolCalls: InstrumentationCheckStatusEnumApi,
    userIdentity: InstrumentationCheckStatusEnumApi,
    traceStructure: InstrumentationCheckStatusEnumApi
): InstrumentationChecklistApi {
    return {
        window_days: 30,
        checks: [
            SESSIONS[sessions],
            TOOL_CALLS[toolCalls],
            USER_IDENTITY[userIdentity],
            TRACE_STRUCTURE[traceStructure],
        ],
    }
}

function withChecklist(response: InstrumentationChecklistApi): ReturnType<typeof mswDecorator> {
    return mswDecorator({
        get: { '/api/projects/:team_id/ai_observability/instrumentation_checklist/': response },
        post: {
            '/api/projects/:team_id/ai_observability/instrumentation_checklist/dismiss/': {
                ...response,
                checks: response.checks.map((check, index) =>
                    index === 0 ? { ...check, status: InstrumentationCheckStatusEnumApi.Dismissed } : check
                ),
            },
            '/api/projects/:team_id/ai_observability/instrumentation_checklist/restore/': response,
        },
    })
}

const meta: Meta<typeof InstrumentationChecklistCard> = {
    component: InstrumentationChecklistCard,
    title: 'Scenes-App/AI observability/Instrumentation checklist card',
    parameters: {
        layout: 'padded',
        featureFlags: [FEATURE_FLAGS.AI_OBSERVABILITY_INSTRUMENTATION_CHECKLIST],
    },
}
export default meta

type Story = StoryObj<typeof InstrumentationChecklistCard>

export const Warnings: Story = {
    decorators: [
        withChecklist(
            checklist(
                InstrumentationCheckStatusEnumApi.Warning,
                InstrumentationCheckStatusEnumApi.Warning,
                InstrumentationCheckStatusEnumApi.Ok,
                InstrumentationCheckStatusEnumApi.Ok
            )
        ),
    ],
}

export const WarningsWithADismissal: Story = {
    decorators: [
        withChecklist(
            checklist(
                InstrumentationCheckStatusEnumApi.Dismissed,
                InstrumentationCheckStatusEnumApi.Warning,
                InstrumentationCheckStatusEnumApi.Ok,
                InstrumentationCheckStatusEnumApi.Pending
            )
        ),
    ],
}

export const Passing: Story = {
    decorators: [
        withChecklist(
            checklist(
                InstrumentationCheckStatusEnumApi.Ok,
                InstrumentationCheckStatusEnumApi.Ok,
                InstrumentationCheckStatusEnumApi.Ok,
                InstrumentationCheckStatusEnumApi.Ok
            )
        ),
    ],
}

export const Collecting: Story = {
    decorators: [
        withChecklist(
            checklist(
                InstrumentationCheckStatusEnumApi.Pending,
                InstrumentationCheckStatusEnumApi.Pending,
                InstrumentationCheckStatusEnumApi.Pending,
                InstrumentationCheckStatusEnumApi.Pending
            )
        ),
    ],
}

export const FirstLoad: Story = {
    parameters: {
        layout: 'padded',
        featureFlags: [FEATURE_FLAGS.AI_OBSERVABILITY_INSTRUMENTATION_CHECKLIST],
        // The skeleton stands in for a read that has not answered, so it never settles in a story.
        testOptions: { waitForLoadersToDisappear: false },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/ai_observability/instrumentation_checklist/': () => new Promise(() => {}),
            },
        }),
    ],
}
