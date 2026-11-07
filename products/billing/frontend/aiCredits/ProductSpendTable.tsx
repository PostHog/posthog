import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { humanFriendlyCurrency } from 'lib/utils/numbers'

import type { AISpendResponseApi } from 'products/billing/frontend/generated/api.schemas'

import { ChartedProduct } from './aiSpend'

type ProductSpendRow =
    | { kind: 'product'; product: ChartedProduct }
    | { kind: 'total'; freeUsd: string; spendUsd: string }

function free(freeUsd: string): string {
    return Number(freeUsd) > 0 ? `−${humanFriendlyCurrency(freeUsd)}` : '–'
}

export interface ProductSpendTableProps {
    spend: AISpendResponseApi
    products: ChartedProduct[]
}

export function ProductSpendTable({ spend, products }: ProductSpendTableProps): JSX.Element {
    const rows: ProductSpendRow[] = [
        ...products.map((product): ProductSpendRow => ({ kind: 'product', product })),
        { kind: 'total', freeUsd: spend.free_usd, spendUsd: spend.spend_usd },
    ]

    const columns: LemonTableColumns<ProductSpendRow> = [
        {
            title: 'Product',
            key: 'product',
            render: (_, row) =>
                row.kind === 'total' ? (
                    <span className="font-semibold">Charged to balance</span>
                ) : (
                    <span className="flex items-center gap-2.5">
                        {/* The swatch takes the product's chart color, which no utility class can hold. */}
                        <span className="size-2.5 shrink-0 rounded-xs" style={{ backgroundColor: row.product.color }} />
                        <span className="font-medium">{row.product.name}</span>
                    </span>
                ),
        },
        {
            title: 'Free',
            key: 'free',
            align: 'right',
            tooltip: 'The list cost minus what your balance paid',
            render: (_, row) => (
                <span className="text-secondary">
                    {free(row.kind === 'total' ? row.freeUsd : row.product.free_usd)}
                </span>
            ),
        },
        {
            title: 'Spend',
            key: 'spend',
            align: 'right',
            render: (_, row) => (
                <span className="font-semibold">
                    {humanFriendlyCurrency(row.kind === 'total' ? row.spendUsd : row.product.spend_usd)}
                </span>
            ),
        },
    ]

    return (
        <div className="rounded border bg-surface-primary">
            <h3 className="m-0 border-b px-5 py-3.5 text-base font-semibold">Spend by product</h3>
            <LemonTable<ProductSpendRow>
                embedded
                dataSource={rows}
                columns={columns}
                rowKey={(row) => (row.kind === 'total' ? 'total' : row.product.product)}
                rowClassName={(row) => (row.kind === 'total' ? 'bg-surface-secondary' : null)}
                emptyState="No AI spend this period yet"
            />
        </div>
    )
}
