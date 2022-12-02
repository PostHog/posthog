import { kea, path, selectors } from 'kea'
import { Breadcrumb, SessionPlayerData } from '~/types'
import { urls } from 'scenes/urls'
import { loaders } from 'kea-loaders'

import type { importSessionRecordingLogicType } from './importSessionRecordingLogicType'
import { beforeUnload } from 'kea-router'
import { lemonToast } from '@posthog/lemon-ui'

export const importSessionRecordingLogic = kea<importSessionRecordingLogicType>([
    path(['scenes', 'session-recordings', 'detail', 'sessionRecordingDetailLogic']),

    loaders({
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
                            alert(e)
                            reject(e)
                        }
                        filereader.readAsText(file)
                    })

                    const data = JSON.parse(loadedFile) as SessionPlayerData

                    if (!data.metadata || !data.snapshotsByWindowId) {
                        throw new Error('File does not appear to be a valid session recording export')
                    }
                    return data
                } catch (error) {
                    lemonToast.error(`File import failed: ${error}`)
                }
            },

            resetSessionRecording: () => null,
        },
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
