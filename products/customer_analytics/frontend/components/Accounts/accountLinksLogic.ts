import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { combineUrl, router } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { accountsPartialUpdate, accountsRetrieve } from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountApi,
    PatchedAccountApiProperties,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import type { accountLinksLogicType } from './accountLinksLogicType'
import { SALESFORCE_ORIGIN } from './constants'

const ORGANIZATION_GROUP_TYPE_INDEX = 0
const REVENUE_DASHBOARD_ID = 259114
const BILLING_ADMIN_ORIGIN = 'https://billing.posthog.com'
const SLACK_ARCHIVES_ORIGIN = 'https://posthog.slack.com/archives'

export interface AccountLinksLogicProps {
    accountId: string
}

export type AccountLinkFieldKey = 'external_id' | 'billing_id' | 'slack_channel_id' | 'usage_dashboard_link' | 'sfdc_id'

export interface AccountLinkFieldDef {
    key: AccountLinkFieldKey
    label: string
    placeholder: string
}

export type AccountLinkFieldValues = Record<AccountLinkFieldKey, string>

export const ACCOUNT_LINK_FIELDS: AccountLinkFieldDef[] = [
    { key: 'external_id', label: 'External ID', placeholder: 'e.g. cust_acme_001' },
    { key: 'billing_id', label: 'Billing ID', placeholder: 'e.g. cus_acme_123' },
    { key: 'slack_channel_id', label: 'Slack channel ID', placeholder: 'e.g. C0123456789' },
    { key: 'usage_dashboard_link', label: 'Usage dashboard link', placeholder: 'https://…' },
    { key: 'sfdc_id', label: 'Salesforce ID', placeholder: 'e.g. 0011t00000AbCdEfGhI' },
]

const EMPTY_FIELDS: AccountLinkFieldValues = {
    external_id: '',
    billing_id: '',
    slack_channel_id: '',
    usage_dashboard_link: '',
    sfdc_id: '',
}

export interface AccountLink {
    key: string
    label: string
    to: string | null
    targetBlank: boolean
    disabledReason: string | null
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
        openEditor: true,
        closeEditor: true,
        setFieldValue: (fieldKey: AccountLinkFieldKey, value: string) => ({ fieldKey, value }),
        setFormValues: (values: AccountLinkFieldValues) => ({ values }),
        saveLinks: true,
        saveStarted: true,
        saveFinished: true,
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
        editorOpen: [
            false,
            {
                openEditor: () => true,
                closeEditor: () => false,
            },
        ],
        formValues: [
            EMPTY_FIELDS,
            {
                setFormValues: (_, { values }) => values,
                setFieldValue: (state, { fieldKey, value }) => ({ ...state, [fieldKey]: value }),
            },
        ],
        savingLinks: [
            false,
            {
                saveStarted: () => true,
                saveFinished: () => false,
            },
        ],
    }),
    selectors({
        currentFieldValues: [
            (s) => [s.account],
            (account: AccountApi | null): AccountLinkFieldValues => ({
                external_id: account?.external_id ?? '',
                billing_id: account?.properties?.billing_id ?? '',
                slack_channel_id: account?.properties?.slack_channel_id ?? '',
                usage_dashboard_link: account?.properties?.usage_dashboard_link ?? '',
                sfdc_id: account?.properties?.sfdc_id ?? '',
            }),
        ],
        links: [
            (s) => [s.account, router.selectors.currentLocation],
            (account: AccountApi | null, currentLocation): AccountLink[] => {
                const externalId = account?.external_id ?? null
                const billingId = account?.properties?.billing_id ?? null
                const slackChannelId = account?.properties?.slack_channel_id ?? null
                const usageDashboardLink = account?.properties?.usage_dashboard_link ?? null
                const sfdcId = account?.properties?.sfdc_id ?? null
                const backUrl =
                    removeProjectIdIfPresent(currentLocation.pathname) + currentLocation.search + currentLocation.hash
                return [
                    {
                        key: 'organization',
                        label: 'Organization',
                        to: externalId
                            ? combineUrl(urls.group(ORGANIZATION_GROUP_TYPE_INDEX, externalId), {
                                  backUrl,
                                  backName: 'Accounts',
                              }).url
                            : null,
                        targetBlank: false,
                        disabledReason: externalId ? null : 'No external ID set',
                    },
                    {
                        key: 'revenue',
                        label: 'Revenue',
                        to: externalId ? revenueDashboardUrl(externalId, billingId) : null,
                        targetBlank: false,
                        disabledReason: externalId ? null : 'No external ID set',
                    },
                    {
                        key: 'usage-dashboard',
                        label: 'Usage dashboard',
                        to: usageDashboardLink,
                        targetBlank: true,
                        disabledReason: usageDashboardLink ? null : 'No usage dashboard link set',
                    },
                    {
                        key: 'slack',
                        label: 'Slack channel',
                        to: slackChannelId ? `${SLACK_ARCHIVES_ORIGIN}/${slackChannelId}` : null,
                        targetBlank: true,
                        disabledReason: slackChannelId ? null : 'No Slack channel set',
                    },
                    {
                        key: 'billing-admin',
                        label: 'Billing admin',
                        to: billingId ? `${BILLING_ADMIN_ORIGIN}/admin/billing/customer/${billingId}/change/` : null,
                        targetBlank: true,
                        disabledReason: billingId ? null : 'No billing ID set',
                    },
                    {
                        key: 'salesforce',
                        label: 'Salesforce',
                        to: sfdcId ? `${SALESFORCE_ORIGIN}/${sfdcId}` : null,
                        targetBlank: true,
                        disabledReason: sfdcId ? null : 'No Salesforce ID set',
                    },
                ]
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        openEditor: () => {
            actions.setFormValues(values.currentFieldValues)
        },
        saveLinks: async () => {
            if (values.savingLinks) {
                return
            }
            const projectId = String(values.currentTeamId)
            const form = values.formValues
            const orNull = (value: string): string | null => value.trim() || null
            actions.saveStarted()
            try {
                const current = await accountsRetrieve(projectId, props.accountId)
                const updated = await accountsPartialUpdate(projectId, props.accountId, {
                    external_id: orNull(form.external_id),
                    properties: {
                        ...current.properties,
                        billing_id: orNull(form.billing_id),
                        slack_channel_id: orNull(form.slack_channel_id),
                        usage_dashboard_link: orNull(form.usage_dashboard_link),
                        sfdc_id: orNull(form.sfdc_id),
                    } as PatchedAccountApiProperties,
                })
                actions.loadAccountSuccess(updated)
                actions.closeEditor()
                lemonToast.success('Links updated')
            } catch (error) {
                posthog.captureException(error as Error, { scope: 'accountLinksLogic.saveLinks' })
                lemonToast.error('Failed to save links')
            } finally {
                actions.saveFinished()
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadAccount()
    }),
])
