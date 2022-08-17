import { kea } from 'kea'
import { EntityTypes, PropertyOperator, RecordingDurationFilter, SessionRecordingId } from '~/types'
import { router } from 'kea-router'
import { eventUsageLogic, RecordingWatchedSource } from 'lib/utils/eventUsageLogic'

import { getDefaultEventName } from 'lib/utils/getAppContext'

import type { sessionPlayerDrawerLogicType } from './sessionPlayerDrawerLogicType'

interface HashParams {
    sessionRecordingId?: SessionRecordingId
}

export const DEFAULT_DURATION_FILTER: RecordingDurationFilter = {
    type: 'recording',
    key: 'duration',
    value: 60,
    operator: PropertyOperator.GreaterThan,
}

export const DEFAULT_PROPERTY_FILTERS = []

const event = getDefaultEventName()

export const DEFAULT_ENTITY_FILTERS = {
    events: [],
    actions: [],
    new_entity: [
        {
            id: event,
            type: EntityTypes.EVENTS,
            order: 0,
            name: event,
        },
    ],
}

export const sessionPlayerDrawerLogic = kea<sessionPlayerDrawerLogicType>({
    path: ['scenes', 'session-recordings', 'sessionPlayerDrawerLogic'],
    connect: {
        actions: [eventUsageLogic, ['reportRecordingsListFetched', 'reportRecordingsListFilterAdded']],
    },
    actions: {
        openSessionPlayer: (sessionRecordingId: SessionRecordingId | null, source: RecordingWatchedSource) => ({
            sessionRecordingId,
            source,
        }),
        closeSessionPlayer: true,
    },
    reducers: {
        activeSessionRecordingId: [
            null as SessionRecordingId | null,
            {
                openSessionPlayer: (_, { sessionRecordingId }) => sessionRecordingId,
                closeSessionPlayer: () => null,
            },
        ],
    },
    actionToUrl: ({ values }) => {
        const buildURL = (
            replace: boolean
        ): [
            string,
            Record<string, any>,
            Record<string, any>,
            {
                replace: boolean
            }
        ] => {
            const hashParams: HashParams = {
                ...router.values.hashParams,
            }

            if (!values.activeSessionRecordingId) {
                delete hashParams.sessionRecordingId
            } else {
                hashParams.sessionRecordingId = values.activeSessionRecordingId
            }

            return [router.values.location.pathname, router.values.searchParams, hashParams, { replace }]
        }

        return {
            openSessionPlayer: ({}) => buildURL(false),
            closeSessionPlayer: () => buildURL(false),
        }
    },

    urlToAction: ({ actions, values, props }) => {
        const urlToAction = (_: any, __: any, hashParams: HashParams): void => {
            const nulledSessionRecordingId = hashParams.sessionRecordingId ?? null
            if (nulledSessionRecordingId !== values.activeSessionRecordingId) {
                actions.openSessionPlayer(nulledSessionRecordingId, RecordingWatchedSource.Direct)
            }
        }
        const urlPattern = props.personUUID ? '/person/*' : '/recordings'
        return {
            [urlPattern]: urlToAction,
        }
    },
})
