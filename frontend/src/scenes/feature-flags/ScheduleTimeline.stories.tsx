import { Meta } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import {
    ScheduledChangeModels,
    ScheduledChangeOperationType,
    ScheduledChangePayload,
    ScheduledChangeRequestState,
    ScheduledChangeType,
    UserBasicType,
} from '~/types'

import { ScheduleOccurrence, ScheduleProjectedState } from './scheduleOccurrences'
import { ScheduleTimeline } from './ScheduleTimeline'

const MOCK_NOW = '2026-08-24T12:00:00Z'

const meta: Meta<typeof ScheduleTimeline> = {
    title: 'Scenes-App/Feature Flags/Schedule Timeline',
    component: ScheduleTimeline,
    parameters: { mockDate: MOCK_NOW },
}
export default meta

const STORY_USER: UserBasicType = {
    id: 1,
    uuid: 'user-1',
    distinct_id: 'user-1',
    first_name: 'Story',
    email: 'story@example.com',
}

let nextId = 1

function occurrence(
    daysFromNow: number,
    payload: ScheduledChangePayload,
    projected: ScheduleProjectedState,
    needsApproval = false
): ScheduleOccurrence {
    const timestamp = dayjs(MOCK_NOW).add(daysFromNow, 'day').toISOString()
    const schedule: ScheduledChangeType = {
        id: nextId++,
        team_id: 1,
        record_id: 1,
        model_name: ScheduledChangeModels.FeatureFlag,
        payload,
        scheduled_at: timestamp,
        executed_at: null,
        failure_reason: null,
        created_at: null,
        created_by: STORY_USER,
        is_recurring: false,
        recurrence_interval: null,
        cron_expression: null,
        last_executed_at: null,
        end_date: null,
        change_request: needsApproval ? { id: 'cr-1', state: ScheduledChangeRequestState.Pending } : null,
    }
    return { timestamp, operation: payload.operation, schedule, projected, needsApproval }
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
