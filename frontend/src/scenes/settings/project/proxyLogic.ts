import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { isURL } from 'lib/utils'

import { BaseMemberType, ExplicitTeamMemberType } from '~/types'

import { teamLogic } from '../../teamLogic'
import type { proxyLogicType } from './proxyLogicType'

export type ProxyRecord = {
    domain: string
    status: 'generating' | 'validating' | 'deleted'
    dnsRecords: any
}

export const proxyLogic = kea<proxyLogicType>([
    path(['scenes', 'project', 'Settings', 'proxyLogic']),
    actions(() => ({
        toggleShowingForm: true,
    })),
    reducers(() => ({
        showingForm: [false, { toggleShowingForm: (state) => !state }],
    })),
    loaders(({ values }) => ({
        proxyRecords: {
            __default: [] as ProxyRecord[],
            loadRecords: async () => {
                return await api.get(`api/projects/${teamLogic.values.currentTeamId}/explicit_members/`)
            },
            createRecord: async ({ domain }: { domain: string }) => {
                const newMembers: ExplicitTeamMemberType[] = await api.create(
                    `api/projects/${teamLogic.values.currentTeamId}/explicit_members/`,
                    {
                        domain,
                    }
                )
                lemonToast.success('Created!')
                return [...values.proxyRecords, ...newMembers]
            },
            deleteRecord: async ({ member }: { member: BaseMemberType }) => {
                await api.delete(`api/projects/${teamLogic.values.currentTeamId}/explicit_members/${member.user.uuid}/`)
                return []
            },
        },
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
