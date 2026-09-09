import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { ScheduledChangeOperationType } from '~/types'

import { makeScheduledChange } from './makeScheduledChange'
import { ScheduleOccurrence } from './scheduleOccurrences'
import { ScheduleTimeline } from './ScheduleTimeline'

function occurrence(overrides: Partial<ScheduleOccurrence> = {}): ScheduleOccurrence {
    return {
        timestamp: '2099-08-26T10:22:00Z',
        operation: ScheduledChangeOperationType.UpdateStatus,
        schedule: makeScheduledChange({ scheduled_at: '2099-08-26T10:22:00Z' }),
        projected: { active: true, rolloutPercentage: 50, variantCount: null },
        addedRolloutPercentage: null,
        needsApproval: false,
        ...overrides,
    }
}

describe('ScheduleTimeline', () => {
    // The component reads the wall clock to place marks, so an unpinned clock leaves the fixed
    // fixture dates decades away and squashes every x onto the right edge.
    beforeAll(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2099-08-25T10:22:00Z'))
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    afterEach(() => {
        cleanup()
    })

    it('renders nothing for zero occurrences', () => {
        const { container } = render(<ScheduleTimeline occurrences={[]} currentRolloutPercentage={10} timezone="UTC" />)

        expect(container).toBeEmptyDOMElement()
    })

    it.each([
        { name: 'this year, without the year', overrides: {}, expected: 'Next: enabled on Aug 26, 10:22 AM' },
        {
            name: 'a later year, with the year',
            overrides: { timestamp: '2100-08-26T10:22:00Z' },
            expected: 'Next: enabled on Aug 26, 2100 10:22 AM',
        },
        {
            name: 'a variant change, with a verb',
            overrides: {
                operation: ScheduledChangeOperationType.UpdateVariants,
                projected: { active: true, rolloutPercentage: 50, variantCount: 3 },
            },
            expected: 'Next: switch to 3 variants on Aug 26, 10:22 AM',
        },
    ])('summarizes one occurrence without a chart: $name', ({ overrides, expected }) => {
        const { container } = render(
            <ScheduleTimeline occurrences={[occurrence(overrides)]} currentRolloutPercentage={10} timezone="UTC" />
        )

        expect(screen.getByText(expected)).toBeInTheDocument()
        expect(container.querySelector('svg')).not.toBeInTheDocument()
    })

    it('summarizes an added condition by its own rollout, not the projected max', () => {
        const addCondition = occurrence({
            operation: ScheduledChangeOperationType.AddReleaseCondition,
            addedRolloutPercentage: 10,
            // Projected max stays at an existing 100% condition set; the summary must not report it.
            projected: { active: true, rolloutPercentage: 100, variantCount: null },
        })
        render(<ScheduleTimeline occurrences={[addCondition]} currentRolloutPercentage={100} timezone="UTC" />)

        expect(screen.getByText('Next: add a condition at 10% rollout on Aug 26, 10:22 AM')).toBeInTheDocument()
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

    it('dashes the jump of an approval-blocked step, and not the level before it', () => {
        const { container } = render(
            <ScheduleTimeline
                occurrences={[
                    occurrence({
                        operation: ScheduledChangeOperationType.AddReleaseCondition,
                        projected: { active: true, rolloutPercentage: 50, variantCount: null },
                    }),
                    occurrence({
                        timestamp: '2099-08-28T10:22:00Z',
                        operation: ScheduledChangeOperationType.AddReleaseCondition,
                        projected: { active: true, rolloutPercentage: 75, variantCount: null },
                        needsApproval: true,
                    }),
                ]}
                currentRolloutPercentage={25}
                timezone="UTC"
            />
        )

        const dashed = Array.from(container.querySelectorAll('path[stroke-dasharray]'))
        expect(dashed).toHaveLength(1)
        // A vertical jump only. A dashed horizontal run would claim the flag is not yet at the
        // level it already serves.
        expect(dashed[0].getAttribute('d')).toMatch(/^M [\d.]+ [\d.]+ V [\d.]+$/)
        expect(dashed[0].getAttribute('opacity')).toEqual('0.5')
        // Dash and opacity alone leave a touch user with no way to read the blocked state.
        expect(screen.getByText('75% (needs approval)')).toBeInTheDocument()
        // Nested in the marker's <g>, so RTL's ByTitle query does not reach it.
        expect(container.querySelector('g > title')?.textContent).toEqual('Needs approval')
    })

    it('labels a condition change whose projected rollout is unknown', () => {
        // A flag with no condition sets, and a payload that carries none either, leaves the
        // projection null. The step line cannot plot that, so the marker falls back to a label.
        render(
            <ScheduleTimeline
                occurrences={[
                    occurrence(),
                    occurrence({
                        timestamp: '2099-08-28T10:22:00Z',
                        operation: ScheduledChangeOperationType.AddReleaseCondition,
                        projected: { active: true, rolloutPercentage: null, variantCount: null },
                    }),
                ]}
                currentRolloutPercentage={null}
                timezone="UTC"
            />
        )

        expect(screen.getByText('Condition')).toBeInTheDocument()
        expect(screen.queryByText('0 variants')).not.toBeInTheDocument()
    })

    it('exposes the plan and a focus stop for a user without a mouse', () => {
        const { container } = render(
            <ScheduleTimeline
                occurrences={[
                    occurrence(),
                    occurrence({
                        timestamp: '2099-08-28T10:22:00Z',
                        operation: ScheduledChangeOperationType.AddReleaseCondition,
                        addedRolloutPercentage: 75,
                        projected: { active: true, rolloutPercentage: 75, variantCount: null },
                        needsApproval: true,
                    }),
                ]}
                currentRolloutPercentage={25}
                timezone="UTC"
            />
        )

        // The region scrolls below 600px, and a plain div with overflow takes no arrow keys.
        expect(container.querySelector('[data-attr="feature-flag-schedule-timeline"]')).toHaveAttribute('tabindex', '0')
        // role="img" hides every mark inside the chart, so this label is all a screen reader gets.
        expect(container.querySelector('svg')).toHaveAttribute(
            'aria-label',
            'Timeline of 2 upcoming scheduled changes: enabled on Aug 26, 10:22 AM, then add a condition at 75% rollout on Aug 28, 10:22 AM (needs approval)'
        )
    })
})
