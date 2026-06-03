import { afterMount, connect, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { accountsRetrieve } from 'products/customer_analytics/frontend/generated/api'
import type { AccountApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import type { accountLinksLogicType } from './accountLinksLogicType'

const ORGANIZATION_GROUP_TYPE_INDEX = 0
const REVENUE_DASHBOARD_ID = 259114
const BILLING_ADMIN_ORIGIN = 'https://billing.posthog.com'
const SLACK_ARCHIVES_ORIGIN = 'https://posthog.slack.com/archives'

export interface AccountLinksLogicProps {
    accountId: string
}

export interface AccountLink {
    key: string
    label: string
    to: string
    targetBlank: boolean
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
    selectors({
        links: [
            (s) => [s.account],
            (account: AccountApi | null): AccountLink[] => {
                const externalId = account?.external_id ?? null
                const billingId = account?.properties?.billing_id ?? null
                const slackChannelId = account?.properties?.slack_channel_id ?? null
                const usageDashboardLink = account?.properties?.usage_dashboard_link ?? null
                const links: AccountLink[] = []
                if (externalId) {
                    links.push({
                        key: 'organization',
                        label: 'Organization',
                        to: urls.group(ORGANIZATION_GROUP_TYPE_INDEX, externalId),
                        targetBlank: false,
                    })
                    links.push({
                        key: 'revenue',
                        label: 'Revenue',
                        to: revenueDashboardUrl(externalId, billingId),
                        targetBlank: false,
                    })
                }
                if (usageDashboardLink) {
                    links.push({
                        key: 'usage-dashboard',
                        label: 'Usage dashboard',
                        to: usageDashboardLink,
                        targetBlank: true,
                    })
                }
                if (slackChannelId) {
                    links.push({
                        key: 'slack',
                        label: 'Slack channel',
                        to: `${SLACK_ARCHIVES_ORIGIN}/${slackChannelId}`,
                        targetBlank: true,
                    })
                }
                if (billingId) {
                    links.push({
                        key: 'billing-admin',
                        label: 'Billing admin',
                        to: `${BILLING_ADMIN_ORIGIN}/admin/billing/customer/${billingId}/change/`,
                        targetBlank: true,
                    })
                }
                return links
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadAccount()
    }),
])
