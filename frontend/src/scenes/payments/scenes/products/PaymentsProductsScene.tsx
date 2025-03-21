import { LemonTable } from '@posthog/lemon-ui'
import { PaymentsTabs } from 'scenes/payments/components/PaymentsTabs'

export function PaymentsProductsScene(): JSX.Element {
    return (
        <>
            <PaymentsTabs />
            <h1>Products</h1>
            <LemonTable
                columns={[
                    {
                        dataIndex: 'name',
                        title: 'Name',
                    },
                    {
                        dataIndex: 'price',
                        title: 'Price',
                    },
                    {
                        dataIndex: 'status',
                        title: 'Status',
                    },
                ]}
                dataSource={[
                    {
                        name: 'Product 1',
                        price: 100,
                        status: 'active',
                    },
                    {
                        name: 'Product 2',
                        price: 200,
                        status: 'inactive',
                    },
                ]}
            />
        </>
    )
}
