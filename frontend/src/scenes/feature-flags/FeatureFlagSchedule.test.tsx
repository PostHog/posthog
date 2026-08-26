import { MOCK_DEFAULT_BASIC_USER, MOCK_DEFAULT_PROJECT } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import {
    FeatureFlagType,
    RecurrenceInterval,
    ScheduledChangeModels,
    ScheduledChangeOperationType,
    ScheduledChangeRequestState,
    ScheduledChangeType,
} from '~/types'

import { NEW_FLAG, featureFlagLogic } from './featureFlagLogic'
import FeatureFlagSchedule from './FeatureFlagSchedule'

jest.mock('./FeatureFlagReleaseConditionsCollapsible', () => ({
    FeatureFlagReleaseConditionsCollapsible: () => null,
}))
jest.mock('./FeatureFlagVariantsForm', () => ({ FeatureFlagVariantsForm: () => null }))

const MULTIVARIATE_FILTERS: FeatureFlagType['filters']['multivariate'] = {
    variants: [
        { key: 'control', name: 'Control', rollout_percentage: 50 },
        { key: 'test', name: 'Test', rollout_percentage: 50 },
    ],
}

function buildFeatureFlag({
    active,
    rolloutPercentage,
}: {
    active: boolean
    rolloutPercentage: number | null
}): FeatureFlagType {
    return {
        ...NEW_FLAG,
        id: 1,
        active,
        filters: {
            ...NEW_FLAG.filters,
            groups: [{ properties: [], rollout_percentage: rolloutPercentage, variant: null }],
            multivariate: MULTIVARIATE_FILTERS,
        },
    }
}

describe('FeatureFlagSchedule', () => {
    const logicProps = { id: 'new' as const }

    function renderSchedule(featureFlag: FeatureFlagType, operation: ScheduledChangeOperationType): void {
        const logic = featureFlagLogic(logicProps)

        render(
            <Provider>
                <BindLogic logic={featureFlagLogic} props={logicProps}>
                    <FeatureFlagSchedule />
                </BindLogic>
            </Provider>
        )

        act(() => {
            logic.actions.setFeatureFlag(featureFlag)
            logic.actions.setScheduledChangeOperation(operation)
        })
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team/default_evaluation_contexts/': {
                    default_evaluation_contexts: [],
                    available_contexts: [],
                    hidden_contexts: [],
                    enabled: false,
                },
                '/api/environments/:team/default_release_conditions/': {
                    default_groups: [],
                    enabled: false,
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    // A bad sum is only rejected when the change fires, long after it was scheduled.
    it.each([
        {
            name: 'sums to 100',
            percentages: [50, 50],
            operation: ScheduledChangeOperationType.UpdateVariants,
            expectedDisabled: false,
        },
        {
            name: 'falls short',
            percentages: [50, 20],
            operation: ScheduledChangeOperationType.UpdateVariants,
            expectedDisabled: true,
        },
        {
            name: 'exceeds 100',
            percentages: [60, 60],
            operation: ScheduledChangeOperationType.UpdateVariants,
            expectedDisabled: true,
        },
        // Variants are read from the flag whatever the operation, so a legacy flag stored at 70
        // must still be schedulable for a change that leaves them alone.
        {
            name: 'falls short but the operation leaves variants untouched',
            percentages: [50, 20],
            operation: ScheduledChangeOperationType.UpdateStatus,
            expectedDisabled: false,
        },
    ])('variant rollout $name: Schedule disabled=$expectedDisabled', ({ percentages, operation, expectedDisabled }) => {
        const featureFlag = buildFeatureFlag({ active: true, rolloutPercentage: 100 })
        featureFlag.filters.multivariate = {
            variants: percentages.map((rollout_percentage, index) => ({
                key: `variant-${index}`,
                name: '',
                rollout_percentage,
            })),
        }
        renderSchedule(featureFlag, operation)

        act(() => {
            featureFlagLogic(logicProps).actions.setScheduleDateMarker(dayjs('2030-01-01T00:00:00Z'))
        })

        // LemonButton uses aria-disabled, not the disabled attribute.
        const scheduleButton = screen.getByText('Schedule').closest('button')
        expect(scheduleButton).toHaveAttribute('aria-disabled', String(expectedDisabled))
    })

    it.each([
        {
            name: 'disabled flag',
            featureFlag: buildFeatureFlag({ active: false, rolloutPercentage: 100 }),
            expectedText: 'This flag is currently disabled',
        },
        {
            name: 'zero rollout',
            featureFlag: buildFeatureFlag({ active: true, rolloutPercentage: 0 }),
            expectedText: 'This flag is currently set to 0% rollout on all release conditions',
        },
    ])('warns when updating variants for a $name', ({ featureFlag, expectedText }) => {
        renderSchedule(featureFlag, ScheduledChangeOperationType.UpdateVariants)

        expect(screen.getByText(new RegExp(expectedText))).toBeInTheDocument()
    })

    describe('approval visibility', () => {
        const makeScheduledChange = (overrides: Partial<ScheduledChangeType>): ScheduledChangeType => ({
            id: 1,
            team_id: MOCK_DEFAULT_PROJECT.id,
            record_id: 1,
            model_name: ScheduledChangeModels.FeatureFlag,
            payload: { operation: ScheduledChangeOperationType.UpdateStatus, value: true },
            scheduled_at: '2030-01-01T00:00:00Z',
            executed_at: null,
            failure_reason: null,
            created_at: '2026-01-01T00:00:00Z',
            created_by: MOCK_DEFAULT_BASIC_USER,
            is_recurring: false,
            recurrence_interval: null,
            cron_expression: null,
            last_executed_at: null,
            end_date: null,
            change_request: null,
            ...overrides,
        })

        // useMocks trips the hooks naming lint inside named helpers, so each test registers
        // its own mock before calling this.
        const renderWithSchedules = (): void => {
            renderSchedule(
                buildFeatureFlag({ active: false, rolloutPercentage: 100 }),
                ScheduledChangeOperationType.UpdateStatus
            )
            act(() => {
                featureFlagLogic(logicProps).actions.loadScheduledChanges()
            })
        }

        const schedulesMock = (
            schedules: ScheduledChangeType[]
        ): Record<string, () => [number, { results: ScheduledChangeType[] }]> => ({
            [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/scheduled_changes`]: () => [200, { results: schedules }],
        })

        it('shows the Needs approval tag and an approval link for a pending gated schedule', async () => {
            useMocks({
                get: schedulesMock([
                    makeScheduledChange({
                        change_request: { id: 'cr-pending', state: ScheduledChangeRequestState.Pending },
                    }),
                ]),
            })
            renderWithSchedules()

            expect(await screen.findByText('Needs approval')).toBeInTheDocument()
            const link = screen.getByText('View approval request').closest('a')
            // The router prefixes links with the current project path, so match the suffix only.
            expect(link?.getAttribute('href')).toMatch(/\/approvals\/cr-pending$/)
        })

        it.each([
            { state: ScheduledChangeRequestState.Rejected, expectedTag: 'Rejected' },
            { state: ScheduledChangeRequestState.Expired, expectedTag: 'Approval expired' },
        ])('lists a $state one-time schedule in history with a $expectedTag tag', async ({ state, expectedTag }) => {
            useMocks({ get: schedulesMock([makeScheduledChange({ change_request: { id: 'cr-denied', state } })]) })
            renderWithSchedules()

            fireEvent.click(await screen.findByText('History (1)'))

            expect(await screen.findByText(expectedTag)).toBeInTheDocument()
            expect(screen.queryByText('Active & upcoming')).not.toBeInTheDocument()
        })

        it.each([
            { state: ScheduledChangeRequestState.Rejected, expectedTag: 'Rejected' },
            { state: ScheduledChangeRequestState.Expired, expectedTag: 'Approval expired' },
        ])(
            'keeps a recurring schedule with a $state approval active but tags it $expectedTag',
            async ({ state, expectedTag }) => {
                useMocks({
                    get: schedulesMock([
                        makeScheduledChange({
                            is_recurring: true,
                            recurrence_interval: RecurrenceInterval.Daily,
                            change_request: { id: 'cr-recurring', state },
                        }),
                    ]),
                })
                renderWithSchedules()

                expect(await screen.findByText(expectedTag)).toBeInTheDocument()
                expect(screen.getByText('Active & upcoming')).toBeInTheDocument()
                expect(screen.queryByText(/^History \(/)).not.toBeInTheDocument()
                // The link is the way to unblock a stalled recurring schedule.
                expect(screen.getByText('View approval request')).toBeInTheDocument()
            }
        )

        it('shows the failure reason as visible text on an errored schedule', async () => {
            const failureReason = 'Feature flag not found (will retry automatically, 2 attempts remaining)'
            useMocks({ get: schedulesMock([makeScheduledChange({ failure_reason: failureReason })]) })
            renderWithSchedules()

            expect(await screen.findByText('Error')).toBeInTheDocument()
            expect(screen.getByText(failureReason)).toBeVisible()
        })
    })

    it.each([
        {
            name: 'another operation',
            featureFlag: buildFeatureFlag({ active: false, rolloutPercentage: 0 }),
            operation: ScheduledChangeOperationType.UpdateStatus,
        },
        {
            name: 'nonzero rollout',
            featureFlag: buildFeatureFlag({ active: true, rolloutPercentage: 1 }),
            operation: ScheduledChangeOperationType.UpdateVariants,
        },
        {
            name: 'implicit rollout',
            featureFlag: buildFeatureFlag({ active: true, rolloutPercentage: null }),
            operation: ScheduledChangeOperationType.UpdateVariants,
        },
        {
            name: 'non-multivariate flag',
            featureFlag: {
                ...buildFeatureFlag({ active: false, rolloutPercentage: 0 }),
                filters: { ...NEW_FLAG.filters, multivariate: null },
            },
            operation: ScheduledChangeOperationType.UpdateVariants,
        },
    ])('does not warn for $name', ({ featureFlag, operation }) => {
        renderSchedule(featureFlag, operation)

        expect(screen.queryByText(/Updating variants alone won't make the rollout go live/)).not.toBeInTheDocument()
    })
})
