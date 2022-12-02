import { kea, path, selectors } from 'kea'
import { Breadcrumb, SessionPlayerData } from '~/types'
import { urls } from 'scenes/urls'
import { loaders } from 'kea-loaders'

import type { importSessionRecordingLogicType } from './importSessionRecordingLogicType'
import { beforeUnload } from 'kea-router'

export const importSessionRecordingLogic = kea<importSessionRecordingLogicType>([
    path(['scenes', 'session-recordings', 'detail', 'sessionRecordingDetailLogic']),

    loaders({
        sessionRecording: {
            __default: null as SessionPlayerData | null,
            loadFromFile: async (file: File) => {
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

                return JSON.parse(loadedFile) as SessionPlayerData
            },
        },
    }),

    beforeUnload(({ values, actions }) => ({
        enabled: () => !!values.sessionRecording,
        message: 'The loaded session recording will be lost. Are you sure you want to leave?',
        onConfirm: () => {},
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
