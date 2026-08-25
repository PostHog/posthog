import { cleanup, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { AIObservabilitySessionsEmptyState } from './AIObservabilitySessionsEmptyState'
import { aiObservabilitySharedLogic } from './aiObservabilitySharedLogic'
import { aiObservabilityInstrumentationChecklistRetrieve } from './generated/api'
import {
    AIObservabilityInstrumentationCheckEnumApi,
    InstrumentationCheckStatusEnumApi,
    InstrumentationChecklistApi,
} from './generated/api.schemas'
import { instrumentationChecklistLogic } from './instrumentationChecklist/instrumentationChecklistLogic'
import { hasRecentAIEvents } from './utils/aiEvents'

jest.mock('lib/api')
jest.mock('./utils/aiEvents')
jest.mock('./generated/api', () => ({
    ...jest.requireActual('./generated/api'),
    aiObservabilityInstrumentationChecklistRetrieve: jest.fn(),
}))

const mockRetrieve = aiObservabilityInstrumentationChecklistRetrieve as jest.MockedFunction<
    typeof aiObservabilityInstrumentationChecklistRetrieve
>
const mockHasRecentAIEvents = hasRecentAIEvents as jest.MockedFunction<typeof hasRecentAIEvents>

const GENERIC_COPY = 'No sessions yet'
const INSTRUMENTATION_HEADING = 'Traces are not grouped into sessions'
const SESSIONS_DETAIL = 'No traces include $ai_session_id.'
const DOCS_URL = 'https://posthog.com/docs/ai-observability/sessions'

function checklistWith(status: InstrumentationCheckStatusEnumApi): InstrumentationChecklistApi {
    return {
        window_days: 30,
        checks: [
            {
                key: AIObservabilityInstrumentationCheckEnumApi.Sessions,
                status,
                title: 'Sessions',
                detail: SESSIONS_DETAIL,
                docs_url: DOCS_URL,
                stats: { generations: 100, events_with_session: 0, events_declining_session: 0 },
            },
        ],
    }
}

const MODEL_FILTER: AnyPropertyFilter = {
    type: PropertyFilterType.Event,
    key: '$ai_model',
    operator: PropertyOperator.Exact,
    value: ['gpt-4o'],
}

describe('AIObservabilitySessionsEmptyState', () => {
    let checklistLogic: ReturnType<typeof instrumentationChecklistLogic.build>
    let sharedLogic: ReturnType<typeof aiObservabilitySharedLogic.build>

    beforeEach(async () => {
        jest.clearAllMocks()
        // `dateFilter` persists, so a range set by one case would otherwise be the next one's default.
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

    it('names the missing instrumentation on an unfiltered view', () => {
        render(<AIObservabilitySessionsEmptyState />)

        expect(screen.getByText(INSTRUMENTATION_HEADING)).not.toBeNull()
        expect(screen.getByText(SESSIONS_DETAIL)).not.toBeNull()
        expect(screen.getByText('Learn more').closest('a')?.getAttribute('href')).toBe(DOCS_URL)
        expect(screen.queryByText(GENERIC_COPY)).toBeNull()
    })

    // Without `$ai_session_id` the Sessions query drops every row whatever the range, so the
    // verdict still explains the empty list anywhere inside the 30 days it graded.
    it.each([
        ['the range is the last 24 hours', (): void => sharedLogic.actions.setDates('-24h', null)],
        ['the range is the last 7 days', (): void => sharedLogic.actions.setDates('-7d', null)],
        ['the range is exactly the checklist window', (): void => sharedLogic.actions.setDates('-30d', null)],
        ['an end date closes the range early', (): void => sharedLogic.actions.setDates('-7d', '-1d')],
    ])('names the missing instrumentation when %s', (_, applyFilter) => {
        applyFilter()

        render(<AIObservabilitySessionsEmptyState />)

        expect(screen.getByText(SESSIONS_DETAIL)).not.toBeNull()
        expect(screen.queryByText(GENERIC_COPY)).toBeNull()
    })

    // Blaming instrumentation for a view the user narrowed themselves is the false accusation this
    // whole feature has to avoid, and a range reaching past the graded window is data the verdict
    // never looked at.
    it.each([
        ['a property filter is applied', (): void => sharedLogic.actions.setPropertyFilters([MODEL_FILTER])],
        ['test accounts are filtered out', (): void => sharedLogic.actions.setShouldFilterTestAccounts(true)],
        [
            'the range starts one day before the checklist window',
            (): void => sharedLogic.actions.setDates('-31d', null),
        ],
        ['the range starts before the checklist window', (): void => sharedLogic.actions.setDates('-6m', null)],
        ['the range covers all time', (): void => sharedLogic.actions.setDates('all', null)],
        ['the range has no start at all', (): void => sharedLogic.actions.setDates(null, null)],
    ])('keeps the generic copy when %s', (_, applyFilter) => {
        applyFilter()

        render(<AIObservabilitySessionsEmptyState />)

        expect(screen.getByText(GENERIC_COPY)).not.toBeNull()
        expect(screen.queryByText(SESSIONS_DETAIL)).toBeNull()
    })

    it.each([
        InstrumentationCheckStatusEnumApi.Ok,
        InstrumentationCheckStatusEnumApi.Pending,
        InstrumentationCheckStatusEnumApi.Dismissed,
    ])('keeps the generic copy when the check graded %s', async (status) => {
        mockRetrieve.mockResolvedValue(checklistWith(status))
        checklistLogic.actions.loadInstrumentationChecklist()
        await expectLogic(checklistLogic).toDispatchActions(['loadInstrumentationChecklistSuccess'])

        render(<AIObservabilitySessionsEmptyState />)

        expect(screen.getByText(GENERIC_COPY)).not.toBeNull()
        expect(screen.queryByText(SESSIONS_DETAIL)).toBeNull()
    })
})
