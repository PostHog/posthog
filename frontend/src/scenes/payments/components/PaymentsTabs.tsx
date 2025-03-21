import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { urls } from 'scenes/urls'

import { PaymentsTab } from '~/types'

import { paymentsSceneLogic } from '../scenes/paymentsSceneLogic'

const PAYMENTS_TABS: LemonTab<PaymentsTab>[] = [
    {
        key: PaymentsTab.Overview,
        label: 'Overview',
        link: urls.paymentsOverview(),
    },
    {
        key: PaymentsTab.Products,
        label: 'Products',
        link: urls.paymentsProducts(),
    },
    {
        key: PaymentsTab.Transactions,
        label: 'Transactions',
        link: urls.paymentsTransactions(),
    },
    {
        key: PaymentsTab.Settings,
        label: 'Settings',
        link: urls.paymentsSettings(),
    },
]

export function PaymentsTabs(): JSX.Element {
    const { setTab } = useActions(paymentsSceneLogic)
    const { tab } = useValues(paymentsSceneLogic)
    return (
        <>
            <PageHeader
                tabbedPage
                buttons={
                    <>
                        {tab === PaymentsTab.Products && (
                            <LemonButton type="primary" to={urls.paymentsProducts()} data-attr="new-product">
                                New product
                            </LemonButton>
                        )}
                    </>
                }
            />
            <LemonTabs activeKey={tab} onChange={(t) => setTab(t)} tabs={PAYMENTS_TABS} />
        </>
    )
}
