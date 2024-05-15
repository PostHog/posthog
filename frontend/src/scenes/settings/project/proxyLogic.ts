import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { isURL } from 'lib/utils'
import { organizationLogic } from 'scenes/organizationLogic'

import type { proxyLogicType } from './proxyLogicType'

export type ProxyRecord = {
    id: string
    domain: string
    status: 'waiting' | 'issuing' | 'valid' | 'erroring'
    dnsRecords: any
}

type FormState = 'collapsed' | 'active' | 'complete'

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
                return response
            },
            deleteRecord: async (id: ProxyRecord['id']) => {
                void api.delete(`api/organizations/${values.currentOrganization?.id}/proxy_records/${id}`)
                lemonToast.error('Record deleted')

                let nextRecords = [...values.proxyRecords]
                nextRecords = nextRecords.filter((r) => r.id != id)

                return nextRecords
            },
        },
    })),
    listeners(({ actions }) => ({
        collapseForm: () => actions.loadRecords(),
        deleteRecordFailure: () => actions.loadRecords(),
    })),
    selectors(() => ({})),
    forms(({ actions }) => ({
        createRecord: {
            defaults: { domain: '' },
            errors: ({ domain }) => ({
                domain: !isURL(domain)
                    ? 'Please enter a URL'
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
])
