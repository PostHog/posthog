import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { accountsPartialUpdate, accountsRetrieve } from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountApi,
    PatchedAccountApiProperties,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import type { accountLinksLogicType } from './accountLinksLogicType'

const ORGANIZATION_GROUP_TYPE_INDEX = 0
const REVENUE_DASHBOARD_ID = 259114
const BILLING_ADMIN_ORIGIN = 'https://billing.posthog.com'
const SLACK_ARCHIVES_ORIGIN = 'https://posthog.slack.com/archives'

export interface AccountLinksLogicProps {
    accountId: string
}

export type AccountConfigFieldKey = 'external_id' | 'billing_id' | 'slack_channel_id' | 'usage_dashboard_link'

export interface AccountConfigField {
    key: AccountConfigFieldKey
    label: string
    placeholder: string
}

export interface AccountLink {
    key: string
    label: string
    to: string | null
    targetBlank: boolean
    disabledReason: string | null
    configField: AccountConfigField | null
}

const CONFIG_FIELDS: Record<AccountConfigFieldKey, AccountConfigField> = {
    external_id: { key: 'external_id', label: 'Set external ID', placeholder: 'e.g. cust_acme_001' },
    usage_dashboard_link: { key: 'usage_dashboard_link', label: 'Set usage dashboard link', placeholder: 'https://…' },
    slack_channel_id: { key: 'slack_channel_id', label: 'Set Slack channel ID', placeholder: 'e.g. C0123456789' },
    billing_id: { key: 'billing_id', label: 'Set billing ID', placeholder: 'e.g. cus_acme_123' },
}

function revenueDashboardUrl(externalId: string, billingId: string | null): string {
    const queryVariables = JSON.stringify({ customer_id: billingId, organization_id: externalId })
    return `${urls.dashboard(REVENUE_DASHBOARD_ID)}?query_variables=${encodeURIComponent(queryVariables)}`
}

export const accountLinksLogic = kea<accountLinksLogicType>([
    path((key) => ['scenes', 'customerAnalytics', 'accounts', 'accountLinksLogic', key]),
    props({} as AccountLinksLogicProps),
    key((props) => props.accountId),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    actions({
        updateAccountField: (fieldKey: AccountConfigFieldKey, value: string) => ({ fieldKey, value }),
        fieldUpdateStarted: (fieldKey: AccountConfigFieldKey) => ({ fieldKey }),
        fieldUpdateFinished: (fieldKey: AccountConfigFieldKey) => ({ fieldKey }),
    }),
    loaders(({ props, values }) => ({
        account: [
            null as AccountApi | null,
            {
                loadAccount: async (): Promise<AccountApi | null> => {
                    try {
                        return await accountsRetrieve(String(values.currentTeamId), props.accountId)
                    } catch (error) {
                        posthog.captureException(error as Error, { scope: 'accountLinksLogic.loadAccount' })
                        return null
                    }
                },
            },
        ],
    })),
    reducers({
        savingFields: [
            {} as Record<string, true>,
            {
                fieldUpdateStarted: (state, { fieldKey }) => ({ ...state, [fieldKey]: true }),
                fieldUpdateFinished: (state, { fieldKey }) => {
                    const next = { ...state }
                    delete next[fieldKey]
                    return next
                },
            },
        ],
    }),
    selectors({
        isFieldSaving: [
            (s) => [s.savingFields],
            (savingFields: Record<string, true>) =>
                (fieldKey: AccountConfigFieldKey): boolean =>
                    !!savingFields[fieldKey],
        ],
        links: [
            (s) => [s.account],
            (account: AccountApi | null): AccountLink[] => {
                const externalId = account?.external_id ?? null
                const billingId = account?.properties?.billing_id ?? null
                const slackChannelId = account?.properties?.slack_channel_id ?? null
                const usageDashboardLink = account?.properties?.usage_dashboard_link ?? null
                return [
                    {
                        key: 'organization',
                        label: 'Organization',
                        to: externalId ? urls.group(ORGANIZATION_GROUP_TYPE_INDEX, externalId) : null,
                        targetBlank: false,
                        disabledReason: externalId ? null : 'No external ID set',
                        configField: externalId ? null : CONFIG_FIELDS.external_id,
                    },
                    {
                        key: 'revenue',
                        label: 'Revenue',
                        to: externalId ? revenueDashboardUrl(externalId, billingId) : null,
                        targetBlank: false,
                        disabledReason: externalId ? null : 'No external ID set',
                        configField: externalId ? null : CONFIG_FIELDS.external_id,
                    },
                    {
                        key: 'usage-dashboard',
                        label: 'Usage dashboard',
                        to: usageDashboardLink,
                        targetBlank: true,
                        disabledReason: usageDashboardLink ? null : 'No usage dashboard link set',
                        configField: usageDashboardLink ? null : CONFIG_FIELDS.usage_dashboard_link,
                    },
                    {
                        key: 'slack',
                        label: 'Slack channel',
                        to: slackChannelId ? `${SLACK_ARCHIVES_ORIGIN}/${slackChannelId}` : null,
                        targetBlank: true,
                        disabledReason: slackChannelId ? null : 'No Slack channel set',
                        configField: slackChannelId ? null : CONFIG_FIELDS.slack_channel_id,
                    },
                    {
                        key: 'billing-admin',
                        label: 'Billing admin',
                        to: billingId ? `${BILLING_ADMIN_ORIGIN}/admin/billing/customer/${billingId}/change/` : null,
                        targetBlank: true,
                        disabledReason: billingId ? null : 'No billing ID set',
                        configField: billingId ? null : CONFIG_FIELDS.billing_id,
                    },
                ]
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        updateAccountField: async ({ fieldKey, value }) => {
            if (values.isFieldSaving(fieldKey)) {
                return
            }
            const trimmed = value.trim()
            if (!trimmed) {
                return
            }
            const projectId = String(values.currentTeamId)
            actions.fieldUpdateStarted(fieldKey)
            try {
                const current = await accountsRetrieve(projectId, props.accountId)
                const body =
                    fieldKey === 'external_id'
                        ? { external_id: trimmed }
                        : { properties: { ...current.properties, [fieldKey]: trimmed } as PatchedAccountApiProperties }
                const updated = await accountsPartialUpdate(projectId, props.accountId, body)
                actions.loadAccountSuccess(updated)
            } catch (error) {
                posthog.captureException(error as Error, { scope: 'accountLinksLogic.updateAccountField' })
                lemonToast.error('Failed to save')
            } finally {
                actions.fieldUpdateFinished(fieldKey)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadAccount()
    }),
])
