import { MOCK_DEFAULT_BASIC_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { ScheduledChangeModels, ScheduledChangeOperationType, ScheduledChangeType } from '~/types'

import { ScheduleOccurrence } from './scheduleOccurrences'
import { ScheduleTimeline } from './ScheduleTimeline'

function occurrence(overrides: Partial<ScheduleOccurrence> = {}): ScheduleOccurrence {
    const schedule: ScheduledChangeType = {
        id: 1,
        team_id: 1,
        record_id: 1,
        model_name: ScheduledChangeModels.FeatureFlag,
        payload: { operation: ScheduledChangeOperationType.UpdateStatus, value: true },
        scheduled_at: '2099-08-26T10:22:00Z',
        executed_at: null,
        failure_reason: null,
        created_at: null,
        created_by: MOCK_DEFAULT_BASIC_USER,
        is_recurring: false,
        recurrence_interval: null,
        cron_expression: null,
        last_executed_at: null,
        end_date: null,
        change_request: null,
    }
    return {
        timestamp: '2099-08-26T10:22:00Z',
        operation: ScheduledChangeOperationType.UpdateStatus,
        schedule,
        projected: { active: true, rolloutPercentage: 50, variantCount: null },
        needsApproval: false,
        ...overrides,
    }
}

describe('ScheduleTimeline', () => {
    afterEach(() => {
        cleanup()
    })

    it('renders nothing for zero occurrences', () => {
        const { container } = render(<ScheduleTimeline occurrences={[]} currentRolloutPercentage={10} timezone="UTC" />)

        expect(container).toBeEmptyDOMElement()
    })

    it('renders a summary line without a chart for one occurrence', () => {
        const { container } = render(
            <ScheduleTimeline occurrences={[occurrence()]} currentRolloutPercentage={10} timezone="UTC" />
        )

        expect(screen.getByText('Next: enabled on Aug 26, 2099 10:22 AM')).toBeInTheDocument()
        expect(container.querySelector('svg')).not.toBeInTheDocument()
    })

    it('summarizes an added condition by its own rollout, not the projected max', () => {
        const addCondition = occurrence({
            operation: ScheduledChangeOperationType.AddReleaseCondition,
            schedule: {
                ...occurrence().schedule,
                payload: {
                    operation: ScheduledChangeOperationType.AddReleaseCondition,
                    value: { groups: [{ properties: [], rollout_percentage: 10, variant: null }] },
                },
            },
            // Projected max stays at an existing 100% condition set; the summary must not report it.
            projected: { active: true, rolloutPercentage: 100, variantCount: null },
        })
        render(<ScheduleTimeline occurrences={[addCondition]} currentRolloutPercentage={100} timezone="UTC" />)

        expect(screen.getByText('Next: add a condition at 10% rollout on Aug 26, 2099 10:22 AM')).toBeInTheDocument()
    })

    it('renders the step chart for two or more occurrences', () => {
        const { container } = render(
            <ScheduleTimeline
                occurrences={[
                    occurrence(),
                    occurrence({
                        timestamp: '2099-08-28T10:22:00Z',
                        operation: ScheduledChangeOperationType.AddReleaseCondition,
                        projected: { active: true, rolloutPercentage: 75, variantCount: null },
                    }),
                ]}
                currentRolloutPercentage={10}
                timezone="UTC"
            />
        )

        expect(container.querySelector('svg')).toBeInTheDocument()
        expect(screen.queryByText(/^Next:/)).not.toBeInTheDocument()
    })
})
