import { LemonSelect, LemonSkeleton, LemonTable } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { AccountTopPage, AccountTopPagesResult } from '~/queries/schema/schema-general'

import { filterTopPages, getTopPagesProductOptions } from '../ProductActivity/topPagesPresentation'

const EMPTY_MESSAGES: Record<string, string> = {
    no_group_type: 'Choose an account group type in Customer analytics settings to see top pages here.',
    no_external_id: "This account isn't linked to any activity yet.",
}

export function AccountTopPages({
    result,
    loading,
    productKey,
    onProductKeyChange,
}: {
    result: AccountTopPagesResult
    loading?: boolean
    productKey: string | null
    onProductKeyChange: (productKey: string | null) => void
}): JSX.Element {
    const options = getTopPagesProductOptions(result)
    const pages = filterTopPages(result.pages, options.some(({ key }) => key === productKey) ? productKey : null)

    if (loading && !result.columns.length) {
        return <LemonSkeleton className="h-64 w-full" />
    }
    if (result.emptyReason) {
        return <p className="text-secondary px-4 mb-0">{EMPTY_MESSAGES[result.emptyReason]}</p>
    }
    if (!result.pages.length) {
        return (
            <p className="text-secondary px-4 mb-0" data-attr="account-top-pages-empty">
                No pageviews for this account in the last {result.columns.length} weeks.
            </p>
        )
    }

    return (
        <div
            className={`flex flex-col gap-3 px-2 pb-2 min-w-0 ${loading ? 'opacity-50' : ''}`}
            data-attr="account-top-pages"
        >
            <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-secondary text-xs mb-0">
                    The pages this account viewed most in the app, with each page's latest title.
                </p>
                <LemonSelect<string | null>
                    size="small"
                    value={productKey}
                    onChange={onProductKeyChange}
                    options={[
                        { value: null, label: 'All products' },
                        ...options.map((option) => ({ value: option.key, label: option.label })),
                    ]}
                    data-attr="account-top-pages-product"
                />
            </div>
            <LemonTable<AccountTopPage>
                size="small"
                dataSource={pages}
                rowKey="path"
                pagination={{ pageSize: 15 }}
                columns={[
                    {
                        title: 'Page',
                        key: 'page',
                        render: (_, page) => (
                            <div className="flex flex-col min-w-0 py-1">
                                {page.title && <span className="font-semibold break-words">{page.title}</span>}
                                <span className="font-mono text-xs text-secondary break-all">{page.path}</span>
                            </div>
                        ),
                    },
                    {
                        title: 'Product',
                        key: 'product',
                        render: (_, page) =>
                            page.product
                                ? (result.products.find(({ key }) => key === page.product)?.label ?? page.product)
                                : 'Other',
                    },
                    { title: 'Views', dataIndex: 'views', align: 'right', sorter: (a, b) => a.views - b.views },
                    { title: 'People', dataIndex: 'people', align: 'right', sorter: (a, b) => a.people - b.people },
                    {
                        title: 'Active days',
                        dataIndex: 'activeDays',
                        align: 'right',
                        sorter: (a, b) => a.activeDays - b.activeDays,
                    },
                    {
                        title: 'Last viewed',
                        key: 'lastViewed',
                        render: (_, page) => <TZLabel time={page.lastViewed} />,
                        sorter: (a, b) => a.lastViewed.localeCompare(b.lastViewed),
                    },
                ]}
            />
        </div>
    )
}
