import { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import { billingUnsubscribedJson } from '~/mocks/fixtures/_billing_unsubscribed'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { AvailableFeature, Realm } from '~/types'

import meCurrent from './__mocks__/@me.json'
import { PayGateMini, PayGateMiniProps } from './PayGateMini'

type StoryArgs = PayGateMiniProps & { cloud?: boolean }

const meta: Meta<StoryArgs> = {
    title: 'Components/Pay Gate Mini',
    component: PayGateMini,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-31 12:00:00',
    },
    render: ({ cloud, ...props }) => {
        useStorybookMocks({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    cloud: cloud !== undefined ? cloud : true,
                    is_debug: cloud !== undefined ? cloud : true,
                    realm: Realm.Cloud,
                },
                '/api/billing/': {
                    ...billingJson,
                },
            },
        })

        return (
            <div className="p-10 max-w-4xl mx-auto">
                <PayGateMini {...props}>
                    <></>
                </PayGateMini>
            </div>
        )
    },
}
export default meta

type Story = StoryObj<StoryArgs>

export const PayGateMini_: Story = {
    args: { feature: AvailableFeature.SUBSCRIPTIONS },
}

export const PayGateMiniWithDocsLink: Story = {
    args: { feature: AvailableFeature.SUBSCRIPTIONS, docsLink: 'https://docs.posthog.com/' },
}

export const PayGateMiniWithoutBackground: Story = {
    args: { feature: AvailableFeature.SUBSCRIPTIONS, background: false },
}

export const PayGateMiniSelfHost: Story = {
    args: { feature: AvailableFeature.SUBSCRIPTIONS, cloud: false },
}

export const PayGateMiniContactSales: Story = {
    args: { feature: AvailableFeature.CUSTOM_MSA },
}

export const PayGateMiniGrandfathered: Story = {
    args: { feature: AvailableFeature.SUBSCRIPTIONS, isGrandfathered: true },
}

export const PayGateMiniAddon: Story = {
    args: { feature: AvailableFeature.GROUP_ANALYTICS },
}

export const PayGateMiniLimitFeatureOther: Story = {
    args: { feature: AvailableFeature.ADVANCED_PERMISSIONS, currentUsage: 3 },
    render: ({ cloud, ...props }) => {
        useStorybookMocks({
            get: {
                '/api/users/@me': () => [
                    200,
                    {
                        ...meCurrent,
                        organization: {
                            ...meCurrent.organization,
                            available_product_features: [
                                {
                                    key: 'advanced_permissions',
                                    name: 'Advanced Permissions',
                                },
                            ],
                        },
                    },
                ],
            },
        })

        return (
            <div className="p-10 max-w-4xl mx-auto">
                <PayGateMini {...props}>
                    <></>
                </PayGateMini>
            </div>
        )
    },
}

export const PayGateMiniLimitFeatureProjects: Story = {
    args: { feature: AvailableFeature.ORGANIZATIONS_PROJECTS, currentUsage: 2 },
    render: ({ cloud, ...props }) => {
        useStorybookMocks({
            get: {
                '/api/users/@me': () => [
                    200,
                    {
                        ...meCurrent,
                        organization: {
                            ...meCurrent.organization,
                            available_product_features: [
                                {
                                    key: 'organizations_projects',
                                    name: 'Projects',
                                    limit: 2,
                                },
                            ],
                        },
                    },
                ],
            },
        })

        return (
            <div className="p-10 max-w-4xl mx-auto">
                <PayGateMini {...props}>
                    <></>
                </PayGateMini>
            </div>
        )
    },
}

export const PayGateMiniFree: Story = {
    args: { feature: AvailableFeature.ORGANIZATIONS_PROJECTS, currentUsage: 2 },
    render: ({ cloud, ...props }) => {
        useStorybookMocks({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    cloud: cloud !== undefined ? cloud : true,
                    is_debug: cloud !== undefined ? cloud : true,
                    realm: Realm.Cloud,
                },
                '/api/billing/': {
                    ...billingUnsubscribedJson,
                },
            },
        })

        return (
            <div className="p-10 max-w-4xl mx-auto">
                <PayGateMini {...props}>
                    <></>
                </PayGateMini>
            </div>
        )
    },
}
