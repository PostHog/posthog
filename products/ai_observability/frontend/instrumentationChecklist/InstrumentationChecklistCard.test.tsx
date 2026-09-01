import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import {
    aiObservabilityInstrumentationChecklistDismissCreate,
    aiObservabilityInstrumentationChecklistRestoreCreate,
    aiObservabilityInstrumentationChecklistRetrieve,
} from '../generated/api'
import {
    AIObservabilityInstrumentationCheckEnumApi,
    InstrumentationCheckStatusEnumApi,
    InstrumentationChecklistApi,
} from '../generated/api.schemas'
import { InstrumentationChecklistCard } from './InstrumentationChecklistCard'
import { clearCachedChecklistVerdict, instrumentationChecklistLogic } from './instrumentationChecklistLogic'

jest.mock('../generated/api', () => ({
    aiObservabilityInstrumentationChecklistRetrieve: jest.fn(),
    aiObservabilityInstrumentationChecklistDismissCreate: jest.fn(),
    aiObservabilityInstrumentationChecklistRestoreCreate: jest.fn(),
}))

const mockRetrieve = aiObservabilityInstrumentationChecklistRetrieve as jest.MockedFunction<
    typeof aiObservabilityInstrumentationChecklistRetrieve
>
const mockDismiss = aiObservabilityInstrumentationChecklistDismissCreate as jest.MockedFunction<
    typeof aiObservabilityInstrumentationChecklistDismissCreate
>
const mockRestore = aiObservabilityInstrumentationChecklistRestoreCreate as jest.MockedFunction<
    typeof aiObservabilityInstrumentationChecklistRestoreCreate
>

const CHECK_KEYS = [
    AIObservabilityInstrumentationCheckEnumApi.Sessions,
    AIObservabilityInstrumentationCheckEnumApi.ToolCalls,
    AIObservabilityInstrumentationCheckEnumApi.UserIdentity,
    AIObservabilityInstrumentationCheckEnumApi.TraceStructure,
]
const CHECK_TITLES = ['Sessions', 'Tool calls', 'User identity', 'Trace structure']

function buildChecklist(...statuses: InstrumentationCheckStatusEnumApi[]): InstrumentationChecklistApi {
    return {
        window_days: 30,
        checks: statuses.map((status, index) => ({
            key: CHECK_KEYS[index],
            status,
            title: CHECK_TITLES[index],
            detail: `A sentence about ${CHECK_TITLES[index]}.`,
            docs_url: 'https://posthog.com/docs/ai-observability/installation',
            stats: { generations: 100 },
        })),
    }
}

const { Ok, Warning, Pending, Dismissed } = InstrumentationCheckStatusEnumApi

function toggle(): HTMLElement | null {
    return document.querySelector('[data-attr="ai-observability-instrumentation-checklist-toggle"]')
}

function panel(): Element | null {
    return toggle()?.closest('.LemonCollapsePanel') ?? null
}

// Re-queried on every use: switching a button to disabled adds a tooltip wrapper, which remounts it.
function actionButtons(): HTMLElement[] {
    return Array.from(
        document.querySelectorAll<HTMLElement>(
            [
                '[data-attr="ai-observability-instrumentation-checklist-dismiss"]',
                '[data-attr="ai-observability-instrumentation-checklist-recheck"]',
                '[data-attr="ai-observability-instrumentation-checklist-refresh"]',
            ].join(',')
        )
    )
}

function renderCard(): void {
    render(
        <Provider>
            <InstrumentationChecklistCard />
        </Provider>
    )
}

describe('InstrumentationChecklistCard', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        // Module state by design, so it outlives an unmount and would carry one case into the next.
        clearCachedChecklistVerdict()
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.AI_OBSERVABILITY_INSTRUMENTATION_CHECKLIST]: true,
        })
    })

    afterEach(() => {
        cleanup()
    })

    const loudnessCases: [string, InstrumentationCheckStatusEnumApi[], string][] = [
        ['expands on landing when a check is warning', [Warning, Ok, Ok, Dismissed], 'true'],
        ['collapses when every check passes', [Ok, Ok, Dismissed, Ok], 'false'],
        ['collapses while the checks are still collecting data', [Pending, Pending, Pending, Pending], 'false'],
    ]

    it.each(loudnessCases)('%s', async (_, statuses, expanded) => {
        mockRetrieve.mockResolvedValue(buildChecklist(...statuses))
        renderCard()

        expect(await screen.findByText('Instrumentation checklist')).toBeInTheDocument()
        expect(panel()).toHaveAttribute('aria-expanded', expanded)
    })

    it('stays expandable once every check passes, so a fix can still be verified', async () => {
        mockRetrieve.mockResolvedValue(buildChecklist(Ok, Ok, Ok, Ok))
        renderCard()

        expect(await screen.findByText('Instrumentation checklist')).toBeInTheDocument()
        expect(screen.queryByText('A sentence about Sessions.')).not.toBeInTheDocument()

        await userEvent.click(toggle() as HTMLElement)

        expect(await screen.findByText('A sentence about Sessions.')).toBeInTheDocument()
        expect(panel()).toHaveAttribute('aria-expanded', 'true')
    })

    const noVerdictCases: [string, () => void][] = [
        [
            'the feature flag is off',
            () =>
                featureFlagLogic.actions.setFeatureFlags([], {
                    [FEATURE_FLAGS.AI_OBSERVABILITY_INSTRUMENTATION_CHECKLIST]: false,
                }),
        ],
        ['the read failed', () => mockRetrieve.mockRejectedValue({ status: 500 })],
    ]

    it.each(noVerdictCases)('renders nothing, not a skeleton, while %s', async (_, arrange) => {
        arrange()
        renderCard()

        await expectLogic(instrumentationChecklistLogic).toFinishAllListeners()
        expect(screen.queryByText('Instrumentation checklist')).not.toBeInTheDocument()
        expect(document.querySelector('.LemonSkeleton')).not.toBeInTheDocument()
        expect(screen.queryByText('Could not refresh the checklist.')).not.toBeInTheDocument()
    })

    it('offers a retry when a refresh fails under a checklist already on screen', async () => {
        mockRetrieve.mockResolvedValue(buildChecklist(Warning, Ok, Ok, Ok))
        renderCard()
        await screen.findByText('Instrumentation checklist')

        mockRetrieve.mockRejectedValue({ status: 500 })
        await userEvent.click(screen.getByText('Refresh'))

        expect(await screen.findByText('Could not refresh the checklist.')).toBeInTheDocument()
        expect(screen.getByText('Try again')).toBeInTheDocument()
        expect(screen.getByText('A sentence about Sessions.')).toBeInTheDocument()
    })

    it('offers a recheck on a dismissed row, so a dismissal is not a one-way door', async () => {
        mockRetrieve.mockResolvedValue(buildChecklist(Dismissed, Warning, Ok, Ok))
        mockRestore.mockResolvedValue(buildChecklist(Warning, Warning, Ok, Ok))
        renderCard()

        await userEvent.click(await screen.findByText('Recheck'))

        expect(mockRestore).toHaveBeenCalledWith(expect.any(String), { check: 'sessions' })
        await waitFor(() => expect(screen.queryByText('Recheck')).not.toBeInTheDocument())
    })

    it('blocks every other action while a dismissal is in flight', async () => {
        mockRetrieve.mockResolvedValue(buildChecklist(Warning, Warning, Ok, Dismissed))
        mockDismiss.mockImplementation(() => new Promise(() => {}))
        renderCard()

        await screen.findByText('Instrumentation checklist')
        expect(actionButtons()).toHaveLength(4)
        expect(actionButtons().map((button) => button.getAttribute('aria-disabled'))).toEqual([
            'false',
            'false',
            'false',
            'false',
        ])

        await userEvent.click(actionButtons()[0])

        expect(actionButtons().map((button) => button.getAttribute('aria-disabled'))).toEqual([
            'true',
            'true',
            'true',
            'true',
        ])
        expect(mockDismiss).toHaveBeenCalledTimes(1)
    })
})
