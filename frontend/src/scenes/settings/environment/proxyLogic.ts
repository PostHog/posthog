import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { isDomain } from 'lib/utils'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { organizationLogic } from 'scenes/organizationLogic'

import type { proxyLogicType } from './proxyLogicType'

export type ProxyRecord = {
    id: string
    domain: string
    status: 'waiting' | 'issuing' | 'valid' | 'erroring' | 'deleting'
    message?: string
    target_cname: string
}

export type FormState = 'collapsed' | 'active' | 'complete'

export function domainFor(proxyRecord: ProxyRecord | undefined): string {
    if (!proxyRecord) {
        return apiHostOrigin()
    }

    let domain = proxyRecord.domain
    if (!domain.startsWith('https://')) {
        domain = `https://${domain}`
    }

    return domain
}

export const proxyLogic = kea<proxyLogicType>([
    path(['scenes', 'project', 'Settings', 'proxyLogic']),
    connect(() => ({
        values: [organizationLogic, ['currentOrganization']],
    })),
    actions(() => ({
        collapseForm: true,
        showForm: true,
        completeForm: true,
        maybeRefreshRecords: true,
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
    selectors(() => ({
        shouldRefreshRecords: [
            (s) => [s.proxyRecords],
            (proxyRecords) => {
                return proxyRecords.some((r) => ['waiting', 'issuing', 'deleting'].includes(r.status))
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        collapseForm: () => actions.loadRecords(),
        deleteRecordFailure: () => actions.loadRecords(),
        createRecordSuccess: () => actions.loadRecords(),
        maybeRefreshRecords: () => {
            if (values.shouldRefreshRecords) {
                actions.loadRecords()
            }
        },
    })),
    forms(({ actions }) => ({
        createRecord: {
            defaults: { domain: '' },
            errors: ({ domain }: { domain: string }) => ({
                domain: domain.includes('*')
                    ? 'Domains cannot include wildcards'
                    : !isDomain('http://' + domain)
                      ? 'Do not include the protocol e.g. https://'
                      : !domain.match(/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/)
                        ? "Invalid domain. Please provide a lowercase RFC 1123 subdomain. It must consist of lower case alphanumeric characters, '-' or '.', and must start and end with an alphanumeric character"
                        : undefined,
            }),
            submit: ({ domain }) => {
                actions.createRecord({ domain })
                actions.resetCreateRecord()
            },
        },
    })),
    afterMount(({ actions, cache }) => {
        actions.loadRecords()
        cache.disposables.add(() => {
            const timerId = setInterval(() => actions.maybeRefreshRecords(), 5000)
            return () => clearInterval(timerId)
        }, 'refreshInterval')
    }),
])
