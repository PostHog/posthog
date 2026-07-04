import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { objectsEqual } from 'lib/utils/objects'
import { teamLogic } from 'scenes/teamLogic'

import {
    eventStreamsAddAccountCreate,
    eventStreamsCreate,
    eventStreamsList,
    eventStreamsPartialUpdate,
    eventStreamsRemoveAccountCreate,
    eventStreamsSendTestMessageCreate,
} from 'products/customer_analytics/frontend/generated/api'
import type {
    EventStreamApi,
    EventStreamTestMessageApi,
    PatchedEventStreamApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { AccountsEvents } from '../Accounts/constants'
import type { eventStreamLogicType } from './eventStreamLogicType'

/** What still needs configuring before the stream can deliver to Slack. */
export interface EventStreamDeliveryGaps {
    needsEvents: boolean
    needsSlackChannel: boolean
    needsAccounts: boolean
}

/** Locally staged edits to the stream config, applied on Save. */
export interface EventStreamDraft {
    enabled: boolean
    event_names: string[]
    slack_integration: number | null
    slack_channel_id: string
    slack_channel_name: string
}

function draftFromStream(stream: EventStreamApi | null): EventStreamDraft {
    return {
        enabled: stream?.enabled ?? false,
        event_names: stream?.event_names ?? [],
        slack_integration: stream?.slack_integration ?? null,
        slack_channel_id: stream?.slack_channel_id ?? '',
        slack_channel_name: stream?.slack_channel_name ?? '',
    }
}

export const eventStreamLogic = kea<eventStreamLogicType>([
    path(['products', 'customerAnalytics', 'eventStream', 'eventStreamLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    actions({
        setDraft: (draft: Partial<EventStreamDraft>) => ({ draft }),
        resetDraft: true,
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
                saveEventStream: async (): Promise<EventStreamApi | null> => {
                    const projectId = String(values.currentTeamId)
                    const current = values.eventStream
                    const patch: PatchedEventStreamApi = { ...values.draft }
                    return current
                        ? await eventStreamsPartialUpdate(projectId, current.id, patch)
                        : await eventStreamsCreate(projectId, patch as EventStreamApi)
                },
            },
        ],
        testMessage: [
            null as EventStreamTestMessageApi | null,
            {
                sendTestMessage: async (): Promise<EventStreamTestMessageApi | null> => {
                    const stream = values.eventStream
                    if (!stream?.id) {
                        return null
                    }
                    return await eventStreamsSendTestMessageCreate(String(values.currentTeamId), stream.id)
                },
            },
        ],
    })),
    reducers({
        draft: [
            draftFromStream(null),
            {
                setDraft: (state, { draft }) => ({ ...state, ...draft }),
                loadEventStreamSuccess: (_, { eventStream }) => draftFromStream(eventStream),
                saveEventStreamSuccess: (_, { eventStream }) => draftFromStream(eventStream),
            },
        ],
        membershipUpdatingIds: [
            [] as string[],
            {
                membershipUpdateStarted: (state, { accountId }) => [...state, accountId],
                membershipUpdateFinished: (state, { accountId }) => state.filter((id) => id !== accountId),
            },
        ],
    }),
    selectors({
        hasChanges: [
            (s) => [s.draft, s.eventStream],
            (draft: EventStreamDraft, eventStream: EventStreamApi | null): boolean =>
                !objectsEqual(draft, draftFromStream(eventStream)),
        ],
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
        resetDraft: () => {
            actions.setDraft(draftFromStream(values.eventStream))
        },
        saveEventStreamSuccess: () => {
            lemonToast.success('Event stream configuration saved')
        },
        saveEventStreamFailure: ({ error, errorObject }) => {
            posthog.captureException(errorObject ?? new Error(error), { scope: 'eventStreamLogic.saveEventStream' })
            lemonToast.error('Failed to save the event stream configuration')
        },
        loadEventStreamFailure: ({ error, errorObject }) => {
            posthog.captureException(errorObject ?? new Error(error), { scope: 'eventStreamLogic.loadEventStream' })
        },
        sendTestMessageSuccess: ({ testMessage }) => {
            if (testMessage) {
                const channel = values.eventStream?.slack_channel_name || testMessage.channel_id
                lemonToast.success(`Test message sent to ${channel}`)
            }
        },
        sendTestMessageFailure: ({ error, errorObject }) => {
            posthog.captureException(errorObject ?? new Error(error), { scope: 'eventStreamLogic.sendTestMessage' })
            const detail = (errorObject as { detail?: string } | undefined)?.detail
            lemonToast.error(detail || 'Failed to send the test message')
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
