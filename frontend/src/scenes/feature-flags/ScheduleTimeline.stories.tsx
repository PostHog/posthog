import { Meta } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import { ScheduledChangeOperationType, ScheduledChangePayload, ScheduledChangeRequestState } from '~/types'

import { makeScheduledChange } from './makeScheduledChange'
import { ScheduleOccurrence, ScheduleProjectedState } from './scheduleOccurrences'
import { ScheduleTimeline } from './ScheduleTimeline'

const MOCK_NOW = '2026-08-24T12:00:00Z'

const meta: Meta<typeof ScheduleTimeline> = {
    title: 'Scenes-App/Feature Flags/Schedule Timeline',
    component: ScheduleTimeline,
    parameters: { mockDate: MOCK_NOW },
}
export default meta

function occurrence(
    daysFromNow: number,
    payload: ScheduledChangePayload,
    projected: ScheduleProjectedState,
    needsApproval = false
): ScheduleOccurrence {
    const timestamp = dayjs(MOCK_NOW).add(daysFromNow, 'day').toISOString()
    return {
        timestamp,
        operation: payload.operation,
        schedule: makeScheduledChange({
            payload,
            scheduled_at: timestamp,
            change_request: needsApproval ? { id: 'cr-1', state: ScheduledChangeRequestState.Pending } : null,
        }),
        projected,
        addedRolloutPercentage:
            payload.operation === ScheduledChangeOperationType.AddReleaseCondition ? projected.rolloutPercentage : null,
        needsApproval,
    }
}

function rolloutStep(daysFromNow: number, rollout: number, needsApproval = false): ScheduleOccurrence {
    return occurrence(
        daysFromNow,
        {
            operation: ScheduledChangeOperationType.AddReleaseCondition,
            value: { groups: [{ properties: [], rollout_percentage: rollout, variant: null }] },
        },
        { active: true, rolloutPercentage: rollout, variantCount: null },
        needsApproval
    )
}

export function RolloutRamp(): JSX.Element {
    return (
        <div className="max-w-3xl">
            <ScheduleTimeline
                occurrences={[
                    rolloutStep(1, 25),
                    rolloutStep(3, 50),
                    occurrence(
                        4,
                        { operation: ScheduledChangeOperationType.UpdateVariants, value: { variants: [] } },
                        { active: true, rolloutPercentage: 50, variantCount: 3 }
                    ),
                    rolloutStep(5, 75, true),
                    occurrence(
                        7,
                        { operation: ScheduledChangeOperationType.UpdateStatus, value: false },
                        { active: false, rolloutPercentage: 75, variantCount: 3 }
                    ),
                ]}
                currentRolloutPercentage={10}
                timezone="UTC"
            />
        </div>
    )
}

export function SingleOccurrence(): JSX.Element {
    return (
        <ScheduleTimeline
            occurrences={[
                occurrence(
                    2,
                    { operation: ScheduledChangeOperationType.UpdateStatus, value: true },
                    { active: true, rolloutPercentage: 100, variantCount: null }
                ),
            ]}
            currentRolloutPercentage={100}
            timezone="UTC"
        />
    )
}
