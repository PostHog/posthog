import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { conversationsPlainImportsCreate, conversationsPlainImportsStatusRetrieve } from '../../generated/api'
import type { PlainImportJobApi } from '../../generated/api.schemas'
import type { plainImportLogicType } from './plainImportLogicType'
import { supportSettingsLogic } from './supportSettingsLogic'

export type PlainImportJobStatus = PlainImportJobApi['status']
export type PlainImportRegion = 'uk' | 'us'

const TERMINAL_STATUSES: PlainImportJobStatus[] = ['completed', 'failed']
const POLL_INTERVAL_MS = 3000

export const plainImportLogic = kea<plainImportLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'settings', 'plainImportLogic']),
    connect(() => ({
        values: [supportSettingsLogic, ['emailConfigs']],
        actions: [supportSettingsLogic, ['loadEmailConfigs']],
    })),
    actions({
        setApiKey: (apiKey: string) => ({ apiKey }),
        setRegion: (region: PlainImportRegion) => ({ region }),
        setDefaultEmailChannelId: (defaultEmailChannelId: string | null) => ({ defaultEmailChannelId }),
        submitImport: true,
        startPolling: true,
        stopPolling: true,
    }),
    reducers({
        apiKey: ['', { setApiKey: (_, { apiKey }) => apiKey }],
        region: ['uk' as PlainImportRegion, { setRegion: (_, { region }) => region }],
        defaultEmailChannelId: [
            null as string | null,
            { setDefaultEmailChannelId: (_, { defaultEmailChannelId }) => defaultEmailChannelId },
        ],
    }),
    loaders(({ values }) => ({
        importJob: [
            null as PlainImportJobApi | null,
            {
                loadImportJob: async () => {
                    try {
                        return await conversationsPlainImportsStatusRetrieve(String(getCurrentTeamId()))
                    } catch (error: any) {
                        if (error?.status === 404) {
                            return null
                        }
                        throw error
                    }
                },
                submitImport: async () => {
                    return await conversationsPlainImportsCreate(String(getCurrentTeamId()), {
                        api_key: values.apiKey,
                        region: values.region,
                        default_email_channel_id: values.defaultEmailChannelId,
                    })
                },
            },
        ],
    })),
    selectors({
        isImportRunning: [
            (s) => [s.importJob],
            (importJob: PlainImportJobApi | null): boolean =>
                importJob?.status === 'running' || importJob?.status === 'pending',
        ],
        importProgressLabel: [
            (s) => [s.importJob],
            (importJob: PlainImportJobApi | null): string | null => {
                if (!importJob || (importJob.status !== 'running' && importJob.status !== 'pending')) {
                    return null
                }
                if (importJob.total_tickets > 0) {
                    return `${importJob.processed_tickets.toLocaleString()} / ${importJob.total_tickets.toLocaleString()}`
                }
                return `${importJob.processed_tickets.toLocaleString()} processed`
            },
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        submitImportSuccess: () => {
            lemonToast.success('Plain import started')
            actions.setApiKey('')
            actions.startPolling()
        },
        submitImportFailure: ({ error }) => {
            lemonToast.error(error || 'Failed to start Plain import')
        },
        startPolling: () => {
            actions.stopPolling()
            actions.loadImportJob()
            cache.pollTimerId = setInterval(() => {
                actions.loadImportJob()
            }, POLL_INTERVAL_MS)
        },
        loadImportJobSuccess: ({ importJob }) => {
            if (importJob?.region && values.region === 'uk' && importJob.region !== 'uk') {
                actions.setRegion(importJob.region as PlainImportRegion)
            }
            if (importJob && TERMINAL_STATUSES.includes(importJob.status)) {
                actions.stopPolling()
            } else if (importJob && (importJob.status === 'running' || importJob.status === 'pending')) {
                if (!cache.pollTimerId) {
                    actions.startPolling()
                }
            }
        },
        stopPolling: () => {
            if (cache.pollTimerId) {
                clearInterval(cache.pollTimerId)
                cache.pollTimerId = null
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadImportJob()
        actions.loadEmailConfigs()
    }),
    beforeUnmount(({ actions }) => {
        actions.stopPolling()
    }),
])
