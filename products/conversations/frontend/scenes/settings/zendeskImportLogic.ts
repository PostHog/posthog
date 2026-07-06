import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { conversationsZendeskImportsCreate, conversationsZendeskImportsStatusRetrieve } from '../../generated/api'
import type { ZendeskImportJobApi } from '../../generated/api.schemas'
import { supportSettingsLogic } from './supportSettingsLogic'
import type { zendeskImportLogicType } from './zendeskImportLogicType'

export type ZendeskImportJobStatus = ZendeskImportJobApi['status']

const TERMINAL_STATUSES: ZendeskImportJobStatus[] = ['completed', 'failed']
const POLL_INTERVAL_MS = 3000

export const zendeskImportLogic = kea<zendeskImportLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'settings', 'zendeskImportLogic']),
    connect(() => ({
        values: [supportSettingsLogic, ['emailConfigs']],
        actions: [supportSettingsLogic, ['loadEmailConfigs']],
    })),
    actions({
        setSubdomain: (subdomain: string) => ({ subdomain }),
        setEmailAddress: (emailAddress: string) => ({ emailAddress }),
        setApiToken: (apiToken: string) => ({ apiToken }),
        setDefaultEmailChannelId: (defaultEmailChannelId: string | null) => ({ defaultEmailChannelId }),
        submitImport: true,
        startPolling: true,
        stopPolling: true,
    }),
    reducers({
        subdomain: ['', { setSubdomain: (_, { subdomain }) => subdomain }],
        emailAddress: ['', { setEmailAddress: (_, { emailAddress }) => emailAddress }],
        apiToken: ['', { setApiToken: (_, { apiToken }) => apiToken }],
        // Fallback email channel for tickets whose Zendesk recipient doesn't match a configured
        // support address; null = leave those tickets without an email channel.
        defaultEmailChannelId: [
            null as string | null,
            { setDefaultEmailChannelId: (_, { defaultEmailChannelId }) => defaultEmailChannelId },
        ],
    }),
    loaders(({ values }) => ({
        importJob: [
            null as ZendeskImportJobApi | null,
            {
                loadImportJob: async () => {
                    try {
                        return await conversationsZendeskImportsStatusRetrieve(String(getCurrentTeamId()))
                    } catch (error: any) {
                        if (error?.status === 404) {
                            return null
                        }
                        throw error
                    }
                },
                submitImport: async () => {
                    return await conversationsZendeskImportsCreate(String(getCurrentTeamId()), {
                        subdomain: values.subdomain,
                        email_address: values.emailAddress,
                        api_token: values.apiToken,
                        default_email_channel_id: values.defaultEmailChannelId,
                    })
                },
            },
        ],
    })),
    selectors({
        isImportRunning: [
            // Derive purely from job status — not the shared loaders flag, which is also true during
            // the initial status GET (and the submit POST). Folding loading in here mislabels the
            // pre-first-response window on a fresh page as "Import already running". The submit
            // button uses importJobLoading directly for its loading/disabled state instead.
            (s) => [s.importJob],
            (importJob: ZendeskImportJobApi | null): boolean =>
                importJob?.status === 'running' || importJob?.status === 'pending',
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
    listeners(({ actions, values, cache }) => ({
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
            // Prefill only the account-level subdomain so an admin can see which Zendesk account is
            // configured. The agent email and API token are intentionally never returned (the email
            // is a personal login — don't disclose the prior operator's identity to other admins), so
            // both must be re-entered to start a new import. Only fill an empty input to avoid
            // clobbering what the user is typing when poll refreshes re-fire this.
            if (importJob?.subdomain && !values.subdomain) {
                actions.setSubdomain(importJob.subdomain)
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
