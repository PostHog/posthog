import { isFreeEmail } from 'bloommx'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { LemonDialog } from '@posthog/lemon-ui'

import api from 'lib/api'
import { SetupTaskId } from 'lib/components/ProductSetup'
import { globalSetupLogic } from 'lib/components/ProductSetup/globalSetupLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { isDomain } from 'lib/utils'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { UserType } from '~/types'

import type { proxyLogicType } from './proxyLogicType'

export type ProxyRecord = {
    id: string
    domain: string
    status: 'waiting' | 'issuing' | 'valid' | 'warning' | 'erroring' | 'deleting' | 'timed_out'
    message?: string
    target_cname: string
}

export type FormState = 'collapsed' | 'active'

export type DiagnosticCheckStatus = 'pass' | 'warn' | 'fail' | 'skip'
export type DiagnosticSummaryStatus = 'healthy' | 'warn' | 'fail'
export type DiagnosticRemediationType = 'dns' | 'config' | 'wait' | 'retry'

export type DiagnosticDnsRecord = {
    name: string
    type: string
    value: string
}

export type DiagnosticRemediation = {
    type: DiagnosticRemediationType
    summary: string
    records: DiagnosticDnsRecord[]
}

export type DiagnosticCheckResult = {
    id: string
    name: string
    status: DiagnosticCheckStatus
    detail: string
    remediation?: DiagnosticRemediation | null
}

export type DiagnosticReportSummary = {
    status: DiagnosticSummaryStatus
    primary_issue: string | null
    next_action: string | null
}

export type DiagnosticReport = {
    ran_at: string
    summary: DiagnosticReportSummary
    checks: DiagnosticCheckResult[]
}

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

const RISKY_DOMAIN_PATTERNS = /\bph\.|posthog|analytics|tracking|tracker|pixel|telemetry|measure|collect|beacon/i

function isRiskyDomain(domain: string): boolean {
    return RISKY_DOMAIN_PATTERNS.test(domain)
}

const AVAILABLE_SUGGESTIONS_SUBDOMAIN = ['b', 'd', 'f', 'g', 'j', 'k', 'm', 'n', 'p', 'r', 's', 't', 'v', 'z']

// Suggesting a domain based on the user's email domain, but only if it's not a free email provider (e.g. Gmail, Outlook, etc.)
// since this only makes sense for users with a custom email domain who likely also have a custom domain they can use for the proxy
function initialDomainFor(user: UserType | null): string {
    if (!user?.email) {
        return ''
    }

    const isFree = isFreeEmail(user.email)
    if (isFree) {
        return ''
    }

    const lastIndex = user.email.lastIndexOf('@')
    if (lastIndex === -1 || lastIndex === user.email.length - 1) {
        return ''
    }

    const domain = user.email.substring(lastIndex + 1, user.email.length)
    const subdomain =
        AVAILABLE_SUGGESTIONS_SUBDOMAIN[Math.floor(Math.random() * AVAILABLE_SUGGESTIONS_SUBDOMAIN.length)]
    return `${subdomain}.${domain}`
}

export const proxyLogic = kea<proxyLogicType>([
    path(['scenes', 'project', 'Settings', 'proxyLogic']),
    connect(() => ({
        values: [organizationLogic, ['currentOrganizationId'], userLogic, ['user']],
    })),
    actions(() => ({
        collapseForm: true,
        showForm: true,
        maybeRefreshRecords: true,
        acknowledgeCloudflareOptIn: true,
        setCloudflareOptInChecked: (checked: boolean) => ({ checked }),
        setMaxProxyRecords: (maxProxyRecords: number) => ({ maxProxyRecords }),
        diagnose: (id: ProxyRecord['id']) => ({ id }),
        diagnoseSuccess: (id: ProxyRecord['id'], report: DiagnosticReport) => ({ id, report }),
        diagnoseFailure: (id: ProxyRecord['id'], error: string) => ({ id, error }),
        clearDiagnosticReport: (id: ProxyRecord['id']) => ({ id }),
        setRecordExpanded: (id: ProxyRecord['id'], expanded: boolean) => ({ id, expanded }),
        setRecordActiveTab: (id: ProxyRecord['id'], tab: string) => ({ id, tab }),
    })),
    reducers(() => ({
        formState: ['collapsed' as FormState, { showForm: () => 'active', collapseForm: () => 'collapsed' }],
        cloudflareOptInAcknowledged: [
            false,
            { persist: true },
            {
                acknowledgeCloudflareOptIn: () => true,
            },
        ],
        cloudflareOptInChecked: [
            false,
            {
                setCloudflareOptInChecked: (_, { checked }) => checked,
                acknowledgeCloudflareOptIn: () => false, // Reset when acknowledged
            },
        ],
        maxProxyRecords: [
            2 as number, // default matching backend DEFAULT_MAX_PROXY_RECORDS
            {
                setMaxProxyRecords: (_, { maxProxyRecords }) => maxProxyRecords,
            },
        ],
        diagnosticReports: [
            {} as Record<string, DiagnosticReport>,
            {
                diagnoseSuccess: (state, { id, report }) => ({ ...state, [id]: report }),
                clearDiagnosticReport: (state, { id }) => {
                    const { [id]: _removed, ...rest } = state
                    return rest
                },
            },
        ],
        diagnoseLoadingIds: [
            [] as string[],
            {
                diagnose: (state, { id }) => (state.includes(id) ? state : [...state, id]),
                diagnoseSuccess: (state, { id }) => state.filter((existingId) => existingId !== id),
                diagnoseFailure: (state, { id }) => state.filter((existingId) => existingId !== id),
            },
        ],
        expandedRecordIds: [
            [] as string[],
            {
                setRecordExpanded: (state, { id, expanded }) => {
                    if (expanded) {
                        return state.includes(id) ? state : [...state, id]
                    }
                    return state.filter((existingId) => existingId !== id)
                },
                clearDiagnosticReport: (state, { id }) => state.filter((existingId) => existingId !== id),
            },
        ],
        recordActiveTabs: [
            {} as Record<string, string>,
            {
                setRecordActiveTab: (state, { id, tab }) => ({ ...state, [id]: tab }),
                clearDiagnosticReport: (state, { id }) => {
                    const { [id]: _removed, ...rest } = state
                    return rest
                },
            },
        ],
    })),
    loaders(({ values, actions }) => ({
        proxyRecords: {
            __default: [] as ProxyRecord[],
            loadRecords: async () => {
                const response = await api.get(`api/organizations/${values.currentOrganizationId}/proxy_records`)
                actions.setMaxProxyRecords(response.max_proxy_records)
                return response.results
            },
            createRecord: async ({ domain }: { domain: string }) => {
                const response = await api.create(`api/organizations/${values.currentOrganizationId}/proxy_records`, {
                    domain,
                })
                lemonToast.success('Record created')
                actions.collapseForm()
                return [response, ...values.proxyRecords]
            },
            deleteRecord: async (id: ProxyRecord['id']) => {
                void api.delete(`api/organizations/${values.currentOrganizationId}/proxy_records/${id}`)
                const newRecords = [...values.proxyRecords].map((r) => ({
                    ...r,
                    status: r.id === id ? 'deleting' : r.status,
                }))
                return newRecords
            },
            retryRecord: async (id: ProxyRecord['id']) => {
                await api.create(`api/organizations/${values.currentOrganizationId}/proxy_records/${id}/retry`)
                lemonToast.success('Retry initiated')
                return values.proxyRecords.map((r) => ({
                    ...r,
                    status: r.id === id ? 'waiting' : r.status,
                    message: r.id === id ? undefined : r.message,
                })) as ProxyRecord[]
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
        retryRecordFailure: () => actions.loadRecords(),
        loadRecordsSuccess: ({ proxyRecords }) => {
            // Mark the reverse proxy setup task as completed if any proxy is valid
            const hasValidProxy = proxyRecords.some((r) => r.status === 'valid')
            if (hasValidProxy) {
                globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.SetUpReverseProxy)
            }
        },
        maybeRefreshRecords: () => {
            if (values.shouldRefreshRecords) {
                actions.loadRecords()
            }
        },
        diagnose: async ({ id }) => {
            try {
                const report = (await api.create(
                    `api/organizations/${values.currentOrganizationId}/proxy_records/${id}/diagnose`
                )) as DiagnosticReport
                actions.diagnoseSuccess(id, report)
            } catch (e) {
                const message = e instanceof Error ? e.message : String(e)
                actions.diagnoseFailure(id, message)
                lemonToast.error(`Diagnose failed: ${message}`)
            }
        },
        diagnoseSuccess: ({ id }) => {
            // Auto-expand the row and switch to the Diagnosis tab so the user sees the report immediately.
            actions.setRecordExpanded(id, true)
            actions.setRecordActiveTab(id, 'diagnosis')
        },
    })),
    forms(({ actions, values }) => ({
        createRecord: {
            defaults: { domain: initialDomainFor(values.user) },
            errors: ({ domain }: { domain: string }) => ({
                domain:
                    domain === ''
                        ? 'Domain is required'
                        : domain.includes('*')
                          ? 'Domains cannot include wildcards'
                          : !isDomain('http://' + domain)
                            ? 'Do not include the protocol e.g. https://'
                            : !domain.match(/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/)
                              ? "Invalid domain. Please provide a lowercase RFC 1123 subdomain. It must consist of lower case alphanumeric characters, '-' or '.', and must start and end with an alphanumeric character"
                              : undefined,
            }),
            submit: ({ domain }) => {
                const doSubmit = (): void => {
                    actions.createRecord({ domain })
                    actions.resetCreateRecord()
                }

                if (isRiskyDomain(domain)) {
                    LemonDialog.open({
                        title: 'This domain may be blocked by ad-blockers',
                        width: '25rem',
                        content: `The domain "${domain}" contains a word commonly associated with tracking or analytics. Ad-blockers are likely to block requests to this domain, which will cause data loss. Are you sure you want to proceed?`,
                        primaryButton: {
                            status: 'danger',
                            children: 'Proceed anyway',
                            onClick: doSubmit,
                        },
                        secondaryButton: {
                            children: 'Choose a different domain',
                        },
                    })
                    return
                }

                doSubmit()
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
