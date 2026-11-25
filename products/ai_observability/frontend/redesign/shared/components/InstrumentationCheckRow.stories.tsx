import type { Meta, StoryObj } from '@storybook/react'

import {
    AIObservabilityInstrumentationCheckEnumApi,
    InstrumentationCheckApi,
    InstrumentationCheckStatusEnumApi,
} from '../../../generated/api.schemas'
import { InstrumentationCheckRow } from './InstrumentationCheckRow'

const CHECK: InstrumentationCheckApi = {
    key: AIObservabilityInstrumentationCheckEnumApi.Sessions,
    status: InstrumentationCheckStatusEnumApi.Warning,
    title: 'Sessions',
    detail: 'No traces include $ai_session_id.',
    docs_url: 'https://posthog.com/docs/ai-observability/sessions',
    stats: {},
}

const meta: Meta<typeof InstrumentationCheckRow> = {
    title: 'Scenes-App/AI observability/Shared/Instrumentation check row',
    component: InstrumentationCheckRow,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        check: CHECK,
        pendingCheckKey: null,
        busy: false,
        onDismiss: () => {},
        onRestore: () => {},
    },
}
export default meta

type Story = StoryObj<typeof InstrumentationCheckRow>

export const Warning: Story = {}
export const Pending: Story = {
    args: { check: { ...CHECK, status: InstrumentationCheckStatusEnumApi.Pending } },
}
export const Dismissed: Story = {
    args: { check: { ...CHECK, status: InstrumentationCheckStatusEnumApi.Dismissed } },
}
export const Saving: Story = {
    args: { pendingCheckKey: AIObservabilityInstrumentationCheckEnumApi.Sessions, busy: true },
}
export const NarrowContainer: Story = {
    decorators: [
        (StoryComponent) => (
            <div className="w-60">
                <StoryComponent />
            </div>
        ),
    ],
}
