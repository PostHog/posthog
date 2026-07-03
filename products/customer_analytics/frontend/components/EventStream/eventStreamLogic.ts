import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import {
    eventStreamsAddAccountCreate,
    eventStreamsCreate,
    eventStreamsList,
    eventStreamsPartialUpdate,
    eventStreamsRemoveAccountCreate,
} from 'products/customer_analytics/frontend/generated/api'
import type { EventStreamApi, PatchedEventStreamApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { AccountsEvents } from '../Accounts/constants'
import type { eventStreamLogicType } from './eventStreamLogicType'

/** What still needs configuring before the stream can deliver to Slack. */
export interface EventStreamDeliveryGaps {
    needsEvents: boolean
    needsSlackChannel: boolean
    needsAccounts: boolean
}

export const eventStreamLogic = kea<eventStreamLogicType>([
    path(['products', 'customerAnalytics', 'eventStream', 'eventStreamLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    actions({
        setAccountMembership: (accountId: string, included: boolean) => ({ accountId, included }),
        membershipUpdateStarted: (accountId: string) => ({ accountId }),
        membershipUpdateFinished: (accountId: string) => ({ accountId }),
    }),
    loaders(({ values }) => ({
        eventStream: [
            null as EventStreamApi | null,
            {
                loadEventStream: async (): Promise<EventStreamApi | null> => {
                    const response = await eventStreamsList(String(values.currentTeamId))
                    return response.results[0] ?? null
                },
                // Creates the team's stream on first save, updates it afterwards.
                saveEventStream: async (patch: PatchedEventStreamApi): Promise<EventStreamApi | null> => {
                    const projectId = String(values.currentTeamId)
                    const current = values.eventStream
                    return current
                        ? await eventStreamsPartialUpdate(projectId, current.id, patch)
                        : await eventStreamsCreate(projectId, patch as EventStreamApi)
                },
            },
        ],
    })),
    reducers({
        membershipUpdatingIds: [
            [] as string[],
            {
                membershipUpdateStarted: (state, { accountId }) => [...state, accountId],
                membershipUpdateFinished: (state, { accountId }) => state.filter((id) => id !== accountId),
            },
        ],
    }),
    selectors({
        isAccountInStream: [
            (s) => [s.eventStream],
            (eventStream: EventStreamApi | null) =>
                (accountId: string): boolean =>
                    !!eventStream?.account_ids?.includes(accountId),
        ],
        deliveryGaps: [
            (s) => [s.eventStream],
            (eventStream: EventStreamApi | null): EventStreamDeliveryGaps | null => {
                if (!eventStream?.enabled) {
                    return null
                }
                const gaps: EventStreamDeliveryGaps = {
                    needsEvents: !eventStream.event_names?.length,
                    needsSlackChannel: !eventStream.slack_integration || !eventStream.slack_channel_id,
                    needsAccounts: !eventStream.account_ids?.length,
                }
                return gaps.needsEvents || gaps.needsSlackChannel || gaps.needsAccounts ? gaps : null
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        saveEventStreamFailure: ({ error, errorObject }) => {
            posthog.captureException(errorObject ?? new Error(error), { scope: 'eventStreamLogic.saveEventStream' })
            lemonToast.error('Failed to save the event stream configuration')
        },
        loadEventStreamFailure: ({ error, errorObject }) => {
            posthog.captureException(errorObject ?? new Error(error), { scope: 'eventStreamLogic.loadEventStream' })
        },
        setAccountMembership: async ({ accountId, included }) => {
            const stream = values.eventStream
            if (!stream || values.membershipUpdatingIds.includes(accountId)) {
                return
            }
            actions.membershipUpdateStarted(accountId)
            try {
                const projectId = String(values.currentTeamId)
                const updated = included
                    ? await eventStreamsAddAccountCreate(projectId, stream.id, { account_id: accountId })
                    : await eventStreamsRemoveAccountCreate(projectId, stream.id, { account_id: accountId })
                actions.loadEventStreamSuccess(updated)
                posthog.capture(AccountsEvents.EventStreamMembershipToggled, {
                    account_id: accountId,
                    included,
                    member_count: updated.account_ids?.length ?? 0,
                })
            } catch (error) {
                posthog.captureException(error as Error, { scope: 'eventStreamLogic.setAccountMembership' })
                lemonToast.error('Failed to update the event stream membership')
            } finally {
                actions.membershipUpdateFinished(accountId)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadEventStream()
    }),
])
