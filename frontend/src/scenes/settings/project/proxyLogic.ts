import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { isDomain } from 'lib/utils'
import { organizationLogic } from 'scenes/organizationLogic'

import type { proxyLogicType } from './proxyLogicType'

export type ProxyRecord = {
    id: string
    domain: string
    status: 'waiting' | 'issuing' | 'valid' | 'erroring' | 'deleting'
    target_cname: string
}

export type FormState = 'collapsed' | 'active' | 'complete'

export const proxyLogic = kea<proxyLogicType>([
    path(['scenes', 'project', 'Settings', 'proxyLogic']),
    connect({ values: [organizationLogic, ['currentOrganization']] }),
    actions(() => ({
        collapseForm: true,
        showForm: true,
        completeForm: true,
    })),
    reducers(() => ({
        formState: [
            'collapsed' as FormState,
            { showForm: () => 'active', collapseForm: () => 'collapsed', completeForm: () => 'complete' },
        ],
    })),
    loaders(({ values, actions }) => ({
        proxyRecords: {
            __default: [] as ProxyRecord[],
            loadRecords: async () => {
                return await api.get(`api/organizations/${values.currentOrganization?.id}/proxy_records`)
            },
            createRecord: async ({ domain }: { domain: string }) => {
                const response = await api.create(`api/organizations/${values.currentOrganization?.id}/proxy_records`, {
                    domain,
                })
                lemonToast.success('Record created')
                actions.completeForm()
                return [response, ...values.proxyRecords]
            },
            deleteRecord: async (id: ProxyRecord['id']) => {
                void api.delete(`api/organizations/${values.currentOrganization?.id}/proxy_records/${id}`)
                const newRecords = [...values.proxyRecords].map((r) => ({
                    ...r,
                    status: r.id === id ? 'deleting' : r.status,
                }))
                return newRecords
            },
        },
    })),
    listeners(({ actions, values, cache }) => ({
        collapseForm: () => actions.loadRecords(),
        deleteRecordFailure: () => actions.loadRecords(),
        deleteRecordSuccess: () => actions.loadRecords(),
        createRecordSuccess: () => actions.loadRecords(),
        loadRecordsSuccess: () => {
            const shouldRefresh = values.proxyRecords.some((r) => ['waiting', 'issuing', 'deleting'].includes(r.status))
            if (shouldRefresh) {
                cache.refreshTimeout = setTimeout(() => {
                    actions.loadRecords()
                }, 5000)
            }
        },
    })),
    forms(({ actions }) => ({
        createRecord: {
            defaults: { domain: '' },
            errors: ({ domain }: { domain: string }) => ({
                domain: !isDomain('http://' + domain)
                    ? 'Do not include the protocol e.g. https://'
                    : domain.includes('*')
                    ? 'Domains cannot include wildcards'
                    : undefined,
            }),
            submit: ({ domain }) => {
                actions.createRecord({ domain })
            },
        },
    })),
    afterMount(({ actions }) => {
        actions.loadRecords()
    }),
    beforeUnmount(({ cache }) => {
        if (cache.refreshTimeout) {
            clearTimeout(cache.refreshTimeout)
        }
    }),
])
