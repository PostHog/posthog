import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { NodeKind, SessionData } from '~/queries/schema/schema-general'

import type { sampledSessionsModalLogicType } from './sampledSessionsModalLogicType'

export interface ModalData {
    sessionData: SessionData[]
    stepName: string
    variant: string
}

export const sampledSessionsModalLogic = kea<sampledSessionsModalLogicType>([
    path(['scenes', 'experiments', 'charts', 'funnel', 'sampledSessionsModalLogic']),

    actions({
        openModal: (modalData: ModalData) => ({ modalData }),
        closeModal: true,
        checkRecordingAvailability: (sessionData: SessionData[]) => ({ sessionData }),
    }),

    reducers({
        isOpen: [
            false as boolean,
            {
                openModal: () => true,
                closeModal: () => false,
            },
        ],
        modalData: [
            null as ModalData | null,
            {
                openModal: (_, { modalData }) => modalData,
                closeModal: () => null,
            },
        ],
    }),

    loaders(() => ({
        recordingAvailability: [
            new Map<string, { hasRecording: boolean }>() as Map<string, { hasRecording: boolean }>,
            {
                checkRecordingAvailability: async ({ sessionData }) => {
                    const allSessionIds = Array.from(new Set(sessionData.map((s: SessionData) => s.session_id)))

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

    listeners(({ actions }) => ({
        openModal: ({ modalData }) => {
            if (modalData.sessionData.length > 0) {
                actions.checkRecordingAvailability(modalData.sessionData)
            }
        },
    })),
])
