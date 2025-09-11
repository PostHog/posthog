import { Meta } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import billingUnsubscribedJson from '~/mocks/fixtures/_billing_unsubscribed.json'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { AvailableFeature, Realm } from '~/types'

import { PayGateMini, PayGateMiniProps } from './PayGateMini'
import meCurrent from './__mocks__/@me.json'

const meta: Meta<typeof PayGateMini> = {
    title: 'Components/Pay Gate Mini',
    component: PayGateMini,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-31 12:00:00',
    },
}
export default meta

const Template = ({ cloud, ...props }: PayGateMiniProps & { cloud?: boolean }): JSX.Element => {
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
}

export const PayGateMini_ = (): JSX.Element => {
    return <Template feature={AvailableFeature.SUBSCRIPTIONS} />
}

export const PayGateMiniWithDocsLink = (): JSX.Element => {
    return <Template feature={AvailableFeature.SUBSCRIPTIONS} docsLink="https://docs.posthog.com/" />
}

export const PayGateMiniWithoutBackground = (): JSX.Element => {
    return <Template feature={AvailableFeature.SUBSCRIPTIONS} background={false} />
}

export const PayGateMiniSelfHost = (): JSX.Element => {
    return <Template feature={AvailableFeature.SUBSCRIPTIONS} cloud={false} />
}

export const PayGateMiniContactSales = (): JSX.Element => {
    return <Template feature={AvailableFeature.CUSTOM_MSA} />
}

export const PayGateMiniGrandfathered = (): JSX.Element => {
    return <Template feature={AvailableFeature.SUBSCRIPTIONS} isGrandfathered />
}

export const PayGateMiniAddon = (): JSX.Element => {
    return <Template feature={AvailableFeature.GROUP_ANALYTICS} />
}

export const PayGateMiniLimitFeatureOther = (): JSX.Element => {
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
    return <Template feature={AvailableFeature.ADVANCED_PERMISSIONS} currentUsage={3} />
}

export const PayGateMiniLimitFeatureProjects = (): JSX.Element => {
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
    return <Template feature={AvailableFeature.ORGANIZATIONS_PROJECTS} currentUsage={2} />
}

export const PayGateMiniFree = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/billing/': {
                ...billingUnsubscribedJson,
            },
        },
    })
    return <Template feature={AvailableFeature.ORGANIZATIONS_PROJECTS} currentUsage={2} />
}
