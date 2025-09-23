import { actions, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { NodeKind, SessionData } from '~/queries/schema/schema-general'

import type { sampledSessionsModalLogicType } from './sampledSessionsModalLogicType'

export interface SampledSessionsModalLogicProps {
    sessionData: SessionData[]
}

export const sampledSessionsModalLogic = kea<sampledSessionsModalLogicType>([
    path(['scenes', 'experiments', 'charts', 'funnel', 'sampledSessionsModalLogic']),
    props({} as SampledSessionsModalLogicProps),

    actions({
        setIsOpen: (isOpen: boolean) => ({ isOpen }),
        checkRecordingAvailability: true,
    }),

    reducers({
        isOpen: [
            false as boolean,
            {
                setIsOpen: (_, { isOpen }) => isOpen,
            },
        ],
    }),

    loaders(({ props }) => ({
        recordingAvailability: [
            new Map<string, { hasRecording: boolean }>() as Map<string, { hasRecording: boolean }>,
            {
                checkRecordingAvailability: async () => {
                    const allSessionIds = Array.from(new Set(props.sessionData.map((s: SessionData) => s.session_id)))

                    if (allSessionIds.length === 0) {
                        return new Map()
                    }

                    try {
                        const response = await api.recordings.list({
                            kind: NodeKind.RecordingsQuery,
                            session_ids: allSessionIds,
                            date_from: '-90d',
                            limit: allSessionIds.length,
                        })

                        const availabilityMap = new Map<string, { hasRecording: boolean }>()
                        response.results?.forEach((recording) => {
                            availabilityMap.set(recording.id, {
                                hasRecording: true,
                            })
                        })
                        // Also add entries for sessions without recordings
                        allSessionIds.forEach((sessionId: string) => {
                            if (!availabilityMap.has(sessionId)) {
                                availabilityMap.set(sessionId, { hasRecording: false })
                            }
                        })

                        return availabilityMap
                    } catch (error) {
                        console.error('Failed to check recording availability:', error)
                        return new Map()
                    }
                },
            },
        ],
    })),

    selectors({
        allSessionIds: [
            (_, p) => [p.sessionData],
            (sessionData: SessionData[]): string[] => {
                return Array.from(new Set(sessionData.map((s: SessionData) => s.session_id)))
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        setIsOpen: ({ isOpen }) => {
            if (isOpen && values.allSessionIds.length > 0) {
                actions.checkRecordingAvailability()
            }
        },
    })),
])
