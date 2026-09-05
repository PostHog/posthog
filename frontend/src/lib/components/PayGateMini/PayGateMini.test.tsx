import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { preflightLogic } from 'lib/logic/preflightLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { userLogic } from 'scenes/userLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AvailableFeature, BillingFeatureType, BillingType } from '~/types'

import meCurrent from './__mocks__/@me.json'
import { PayGateMini } from './PayGateMini'

// Label the organizations_projects feature as invites, the billing mismatch seen in production.
// The gate reads its name and icon from product.features, so only that array needs rewriting;
// spreading the rest keeps dayjs fields intact.
function mislabelProjectsFeatures(billing: BillingType): BillingType {
    return {
        ...billing,
        products: billing.products.map((product) => ({
            ...product,
            features: product.features.map((feature: BillingFeatureType) =>
                feature.key === AvailableFeature.ORGANIZATIONS_PROJECTS
                    ? { ...feature, name: 'Invites', icon_key: 'IconMessage' }
                    : feature
            ),
        })),
    }
}

describe('PayGateMini', () => {
    afterEach(cleanup)

    it('names the projects gate from the local key even when billing labels it invites', async () => {
        useMocks({
            get: {
                '/api/billing/': mislabelProjectsFeatures(billingJson),
                '/api/users/@me/': () => [
                    200,
                    {
                        ...meCurrent,
                        organization: {
                            ...meCurrent.organization,
                            available_product_features: [{ key: 'organizations_projects', name: 'Projects', limit: 2 }],
                        },
                    },
                ],
            },
        })
        initKeaTests()
        preflightLogic().mount()
        userLogic().mount()
        billingLogic().mount()
        await waitFor(() => expect(billingLogic.values.billing).not.toBeNull())

        render(
            <Provider>
                <PayGateMini feature={AvailableFeature.ORGANIZATIONS_PROJECTS} currentUsage={2}>
                    <></>
                </PayGateMini>
            </Provider>
        )

        await waitFor(() => expect(screen.getAllByText('Projects').length).toBeGreaterThan(0))
        expect(screen.queryByText('Invites')).not.toBeInTheDocument()
    })
})
