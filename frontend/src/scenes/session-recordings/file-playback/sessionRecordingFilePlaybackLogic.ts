import { connect, kea, path, reducers, selectors } from 'kea'
import { Breadcrumb, SessionPlayerData } from '~/types'
import { urls } from 'scenes/urls'
import { loaders } from 'kea-loaders'

import { beforeUnload } from 'kea-router'
import { lemonToast } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { uuid } from 'lib/utils'

import type { sessionRecordingFilePlaybackLogicType } from './sessionRecordingFilePlaybackLogicType'

export type ExportedSessionRecordingFile = {
    version: '2022-12-02'
    data: SessionPlayerData
}

export const sessionRecordingFilePlaybackLogic = kea<sessionRecordingFilePlaybackLogicType>([
    path(['scenes', 'session-recordings', 'detail', 'sessionRecordingDetailLogic']),
    connect({
        actions: [eventUsageLogic, ['reportRecordingLoadedFromFile']],
    }),

    loaders(({ actions }) => ({
        sessionRecording: {
            __default: null as SessionPlayerData | null,
            loadFromFile: async (file: File) => {
                try {
                    const loadedFile: string = await new Promise((resolve, reject) => {
                        const filereader = new FileReader()
                        filereader.onload = (e) => {
                            resolve(e.target?.result as string)
                        }
                        filereader.onerror = (e) => {
                            reject(e)
                        }
                        filereader.readAsText(file)
                    })

                    const data = JSON.parse(loadedFile) as ExportedSessionRecordingFile

                    if (!data.version || !data.data) {
                        throw new Error('File does not appear to be a valid session recording export')
                    }

                    if (data.version === '2022-12-02') {
                        actions.reportRecordingLoadedFromFile({ success: true })
                        return data.data
                    } else {
                        throw new Error('File version is not supported')
                    }
                } catch (error) {
                    actions.reportRecordingLoadedFromFile({ success: false, error: `${error}` })
                    lemonToast.error(`File import failed: ${error}`)
                    return null
                }
            },

            resetSessionRecording: () => null,
        },
    })),

    reducers({
        playerKey: [
            'file-playback',
            {
                loadFromFileSuccess: () => `file-playback-${uuid()}`,
                resetSessionRecording: () => 'file-playback',
            },
        ],
    }),

    beforeUnload(({ values, actions }) => ({
        enabled: () => !!values.sessionRecording,
        message: 'The loaded session recording will be lost. Are you sure you want to leave?',
        onConfirm: () => {
            actions.resetSessionRecording()
        },
    })),

    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    name: `Recordings`,
                    path: urls.sessionRecordings(),
                },
                {
                    name: 'Import',
                },
            ],
        ],
    }),
])
