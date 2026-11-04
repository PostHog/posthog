import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonMenu, Spinner } from '@posthog/lemon-ui'

import { OverviewGrid } from '~/queries/nodes/OverviewGrid/OverviewGrid'

import { ProductUsageControls } from './ProductUsageControls'
import { ProductUsageFilters } from './ProductUsageFilters'
import { ProductUsageGrid } from './ProductUsageGrid'
import { productUsageGridLogic } from './productUsageGridLogic'
import { ProductUsageQueryEditor } from './ProductUsageQueryEditor'

export function ProductUsageTabContent(): JSX.Element {
    const { source, editorOpen, result, loading, error, saveError, detailsError, details, canUseProducts } =
        useValues(productUsageGridLogic)
    const { openEditor, refresh, clearSource, loadDetails } = useActions(productUsageGridLogic)
    return (
        <div className="flex flex-col gap-3 min-w-0" data-attr="product-activity-tab">
            <div className="flex flex-wrap justify-between items-center gap-2">
                <ProductUsageFilters />
                <div className="flex flex-wrap gap-2">
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconRefresh />}
                        onClick={refresh}
                        loading={loading}
                        disabledReason={!source ? 'Save a source first.' : undefined}
                    >
                        Refresh
                    </LemonButton>
                    {source && (
                        <LemonButton type="secondary" size="small" onClick={() => openEditor(source.kind)}>
                            Edit query
                        </LemonButton>
                    )}
                    {source && (
                        <LemonMenu
                            items={[
                                { label: 'Change to custom query', onClick: () => openEditor('hogql') },
                                ...(canUseProducts
                                    ? [
                                          {
                                              label: 'Use product usage starter',
                                              onClick: () => openEditor('product_usage'),
                                          },
                                      ]
                                    : []),
                                {
                                    label: 'Clear source',
                                    onClick: () =>
                                        LemonDialog.open({
                                            title: 'Clear this source?',
                                            description: 'The saved query will be removed from this browser.',
                                            primaryButton: {
                                                children: 'Clear source',
                                                status: 'danger',
                                                onClick: clearSource,
                                            },
                                            secondaryButton: { children: 'Cancel' },
                                        }),
                                },
                            ]}
                        >
                            <LemonButton type="tertiary" size="small">
                                More
                            </LemonButton>
                        </LemonMenu>
                    )}
                </div>
            </div>
            {(source || editorOpen) && <ProductUsageControls />}
            {!source && !editorOpen && (
                <div className="border rounded p-6 flex flex-col items-start gap-3">
                    <h3 className="m-0">Add a query to show account activity</h3>
                    <p className="mb-0">
                        Choose the data to fetch, run the query, then map the result columns to the table.
                    </p>
                    <div className="flex flex-wrap gap-2">
                        <LemonButton
                            type="primary"
                            onClick={() => openEditor('hogql')}
                            data-attr="product-activity-add-query"
                        >
                            Add query
                        </LemonButton>
                        {canUseProducts && (
                            <LemonButton
                                type="secondary"
                                onClick={() => openEditor('product_usage')}
                                data-attr="product-activity-product-starter"
                            >
                                Product usage starter
                            </LemonButton>
                        )}
                    </div>
                </div>
            )}
            {editorOpen && <ProductUsageQueryEditor />}
            {saveError && !editorOpen && <LemonBanner type="error">{saveError}</LemonBanner>}
            {error && <LemonBanner type="error">{error}</LemonBanner>}
            {loading && !result && <Spinner />}
            {result && (
                <>
                    <OverviewGrid
                        items={[
                            {
                                key: 'accounts',
                                value: result.accounts.results.length,
                                kind: 'unit',
                                caption: 'Filtered accounts',
                            },
                            {
                                key: 'linked',
                                value: result.accounts.results.filter((account) => account.externalId).length,
                                kind: 'unit',
                                caption: 'Linked accounts',
                            },
                            ...(result.matrix
                                ? [
                                      {
                                          key: 'products',
                                          value: new Set(
                                              result.matrix.data
                                                  .filter((cell) => cell.users > 0)
                                                  .map((cell) => cell.series)
                                          ).size,
                                          kind: 'unit' as const,
                                          caption: 'Products used',
                                      },
                                  ]
                                : []),
                        ]}
                        labelFromKey={(key) =>
                            ({ accounts: 'Accounts', linked: 'Linked accounts', products: 'Products used' })[key] ?? key
                        }
                    />
                    {result.accounts.hasMore && (
                        <LemonBanner type="warning">
                            Showing the first 200 matching accounts. Narrow the filters to include the rest.
                        </LemonBanner>
                    )}
                    <ProductUsageGrid />
                </>
            )}
            {(details.people?.truncated || details.firsts?.truncated) && (
                <LemonBanner type="warning">
                    Some user details are missing. Narrow the account filters to see all people and first-use dates.
                </LemonBanner>
            )}
            {detailsError && (
                <LemonBanner
                    type="warning"
                    action={
                        <LemonButton onClick={loadDetails} size="small">
                            Retry
                        </LemonButton>
                    }
                >
                    {detailsError}
                </LemonBanner>
            )}
        </div>
    )
}
