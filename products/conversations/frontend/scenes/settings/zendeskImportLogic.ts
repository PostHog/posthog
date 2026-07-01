import { actions, afterMount, beforeUnmount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { zendeskImportLogicType } from './zendeskImportLogicType'

export type ZendeskImportJobStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface ZendeskImportJobApi {
    id: string
    status: ZendeskImportJobStatus
    total_tickets: number
    processed_tickets: number
    imported_tickets: number
    skipped_tickets: number
    failed_tickets: number
    started_at: string | null
    finished_at: string | null
    latest_error: string | null
    created_at: string
    updated_at: string
}

const TERMINAL_STATUSES: ZendeskImportJobStatus[] = ['completed', 'failed']
const POLL_INTERVAL_MS = 3000

export const zendeskImportLogic = kea<zendeskImportLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'settings', 'zendeskImportLogic']),
    actions({
        setSubdomain: (subdomain: string) => ({ subdomain }),
        setEmailAddress: (emailAddress: string) => ({ emailAddress }),
        setApiToken: (apiToken: string) => ({ apiToken }),
        submitImport: true,
        startPolling: true,
        stopPolling: true,
    }),
    reducers({
        subdomain: ['', { setSubdomain: (_, { subdomain }) => subdomain }],
        emailAddress: ['', { setEmailAddress: (_, { emailAddress }) => emailAddress }],
        apiToken: ['', { setApiToken: (_, { apiToken }) => apiToken }],
    }),
    loaders(({ values }) => ({
        importJob: [
            null as ZendeskImportJobApi | null,
            {
                loadImportJob: async () => {
                    try {
                        return await api.get<ZendeskImportJobApi>('api/conversations/v1/zendesk/import/status')
                    } catch (error: any) {
                        if (error?.status === 404) {
                            return null
                        }
                        throw error
                    }
                },
                submitImport: async () => {
                    return await api.create<ZendeskImportJobApi>('api/conversations/v1/zendesk/import', {
                        subdomain: values.subdomain,
                        email_address: values.emailAddress,
                        api_token: values.apiToken,
                    })
                },
            },
        ],
    })),
    selectors({
        isImportRunning: [
            (s) => [s.importJob, s.importJobLoading],
            (importJob: ZendeskImportJobApi | null, importJobLoading: boolean): boolean =>
                importJobLoading || importJob?.status === 'running' || importJob?.status === 'pending',
        ],
        importProgressLabel: [
            (s) => [s.importJob],
            (importJob: ZendeskImportJobApi | null): string | null => {
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
    listeners(({ actions, cache }) => ({
        submitImportSuccess: () => {
            lemonToast.success('Zendesk import started')
            actions.setApiToken('')
            actions.startPolling()
        },
        submitImportFailure: ({ error }) => {
            lemonToast.error(error ?? 'Failed to start Zendesk import')
        },
        startPolling: () => {
            actions.stopPolling()
            actions.loadImportJob()
            cache.pollTimerId = setInterval(() => {
                actions.loadImportJob()
            }, POLL_INTERVAL_MS)
        },
        loadImportJobSuccess: ({ importJob }) => {
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
    }),
    beforeUnmount(({ actions }) => {
        actions.stopPolling()
    }),
])
