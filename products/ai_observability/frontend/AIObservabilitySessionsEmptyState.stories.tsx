import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { useStorybookMocks } from '~/mocks/browser'

import { AIObservabilitySessionsEmptyState } from './AIObservabilitySessionsEmptyState'
import {
    AIObservabilityInstrumentationCheckEnumApi,
    InstrumentationCheckStatusEnumApi,
    InstrumentationChecklistApi,
} from './generated/api.schemas'

function checklistWith(status: InstrumentationCheckStatusEnumApi): InstrumentationChecklistApi {
    return {
        window_days: 30,
        checks: [
            {
                key: AIObservabilityInstrumentationCheckEnumApi.Sessions,
                status,
                title: 'Sessions',
                detail:
                    'No traces include $ai_session_id. If your product has multi-turn conversations, setting it ' +
                    'lets us group them into sessions. Workloads that are complete in one trace, like batch jobs ' +
                    'or one-shot generation, do not need it. Send $ai_session_id as null on those to say so.',
                docs_url: 'https://posthog.com/docs/ai-observability/sessions',
                stats: { generations: 1284, events_with_session: 0, events_declining_session: 0 },
            },
        ],
    }
}

const meta: Meta<{ status: InstrumentationCheckStatusEnumApi }> = {
    title: 'Scenes-App/AI observability/Sessions empty state',
    parameters: {
        featureFlags: [FEATURE_FLAGS.AI_OBSERVABILITY_INSTRUMENTATION_CHECKLIST],
        testOptions: { waitForLoadersToDisappear: false },
    },
    render: ({ status }) => {
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/ai_observability/instrumentation_checklist/': checklistWith(status),
            },
        })

        // The list pane the empty state renders into is a narrow, bordered column.
        return (
            <div className="w-[300px] h-[420px] flex flex-col overflow-hidden rounded border border-primary bg-surface-primary">
                <AIObservabilitySessionsEmptyState />
            </div>
        )
    },
}
export default meta
type Story = StoryObj<{ status: InstrumentationCheckStatusEnumApi }>

export const MissingSessionInstrumentation: Story = {
    args: { status: InstrumentationCheckStatusEnumApi.Warning },
}

export const NothingToReport: Story = {
    args: { status: InstrumentationCheckStatusEnumApi.Ok },
}
