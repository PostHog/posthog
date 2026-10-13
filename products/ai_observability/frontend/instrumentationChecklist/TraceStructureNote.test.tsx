import { cleanup, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { LLMTraceEvent } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { aiObservabilitySharedLogic } from '../aiObservabilitySharedLogic'
import { aiObservabilityInstrumentationChecklistRetrieve } from '../generated/api'
import {
    AIObservabilityInstrumentationCheckEnumApi,
    InstrumentationCheckStatusEnumApi,
    InstrumentationChecklistApi,
} from '../generated/api.schemas'
import { hasRecentAIEvents } from '../utils/aiEvents'
import { instrumentationChecklistLogic } from './instrumentationChecklistLogic'
import { TraceStructureNote } from './TraceStructureNote'

jest.mock('lib/api')
jest.mock('../utils/aiEvents')
jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    aiObservabilityInstrumentationChecklistRetrieve: jest.fn(),
}))

const mockRetrieve = aiObservabilityInstrumentationChecklistRetrieve as jest.MockedFunction<
    typeof aiObservabilityInstrumentationChecklistRetrieve
>
const mockHasRecentAIEvents = hasRecentAIEvents as jest.MockedFunction<typeof hasRecentAIEvents>

const NOTE_LABEL = 'No spans in this trace.'
const TRACE_STRUCTURE_DETAIL =
    'Without spans, a trace shows LLM calls but not the retrieval, chains or sub-agent steps around them.'
const DOCS_URL = 'https://posthog.com/docs/ai-observability/installation'

const MODEL_FILTER: AnyPropertyFilter = {
    type: PropertyFilterType.Event,
    key: '$ai_model',
    operator: PropertyOperator.Exact,
    value: ['gpt-4o'],
}

function traceEvent(event: string, properties: Record<string, unknown> = {}): LLMTraceEvent {
    return { id: `${event}-1`, event, properties, createdAt: '2026-01-01T00:00:00Z' }
}

const GENERATIONS_ONLY = [traceEvent('$ai_generation'), traceEvent('$ai_generation')]

function checklistWith(status: InstrumentationCheckStatusEnumApi): InstrumentationChecklistApi {
    return {
        window_days: 30,
        checks: [
            {
                key: AIObservabilityInstrumentationCheckEnumApi.TraceStructure,
                status,
                title: 'Trace structure',
                detail: TRACE_STRUCTURE_DETAIL,
                docs_url: DOCS_URL,
                stats: { total_events: 100, spans: 0, events_with_parent: 0 },
            },
        ],
    }
}

describe('TraceStructureNote', () => {
    let checklistLogic: ReturnType<typeof instrumentationChecklistLogic.build>
    let sharedLogic: ReturnType<typeof aiObservabilitySharedLogic.build>

    beforeEach(async () => {
        jest.clearAllMocks()
        localStorage.clear()
        mockHasRecentAIEvents.mockResolvedValue(true)
        mockRetrieve.mockResolvedValue(checklistWith(InstrumentationCheckStatusEnumApi.Warning))
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.AI_OBSERVABILITY_INSTRUMENTATION_CHECKLIST]: true,
        })
        sharedLogic = aiObservabilitySharedLogic()
        sharedLogic.mount()
        checklistLogic = instrumentationChecklistLogic()
        checklistLogic.mount()
        await expectLogic(checklistLogic).toDispatchActions(['loadInstrumentationChecklistSuccess'])
    })

    afterEach(() => {
        cleanup()
        checklistLogic.unmount()
        sharedLogic.unmount()
        featureFlagLogic.unmount()
    })

    // The list surfaces drop their verdict once a filter is on, since a filter can explain an empty
    // table. Nothing a user narrows can explain a missing span, so this note must survive that state.
    it('names the missing spans even under filters that suppress the tab empty states', () => {
        sharedLogic.actions.setPropertyFilters([MODEL_FILTER])
        sharedLogic.actions.setDates('-6m', null)

        render(<TraceStructureNote events={GENERATIONS_ONLY} />)

        expect(screen.getByText(NOTE_LABEL)).not.toBeNull()
        expect(screen.getByText(TRACE_STRUCTURE_DETAIL, { exact: false })).not.toBeNull()
        expect(screen.getByText('Learn more').closest('a')?.getAttribute('href')).toBe(DOCS_URL)
    })

    // The verdict covers 30 days, while a single trace still renders from beyond that window, so a
    // project that stopped emitting spans can open a trace that visibly has them.
    it.each([
        ['a span', [traceEvent('$ai_generation'), traceEvent('$ai_span')]],
        ['an event nested under a parent', [traceEvent('$ai_generation', { $ai_parent_id: 'trace-1' })]],
    ])('says nothing about a trace that has %s', (_, events) => {
        const { container } = render(<TraceStructureNote events={events} />)

        expect(container.innerHTML).toBe('')
    })

    it.each([
        InstrumentationCheckStatusEnumApi.Ok,
        InstrumentationCheckStatusEnumApi.Pending,
        InstrumentationCheckStatusEnumApi.Dismissed,
    ])('stays out of the way when the check graded %s', async (status) => {
        mockRetrieve.mockResolvedValue(checklistWith(status))
        checklistLogic.actions.loadInstrumentationChecklist()
        await expectLogic(checklistLogic).toDispatchActions(['loadInstrumentationChecklistSuccess'])

        const { container } = render(<TraceStructureNote events={GENERATIONS_ONLY} />)

        expect(container.innerHTML).toBe('')
    })
})
