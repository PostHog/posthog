import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconCursorClick, IconMegaphone } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonDivider, LemonInput, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { createdAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { cn } from 'lib/utils/css-classes'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { urls } from 'scenes/urls'

import { ProductTour, ProgressStatus } from '~/types'

import {
    ProductToursTabs,
    getProductTourStatus,
    isAnnouncement,
    isProductTourRunning,
    productToursLogic,
} from '../productToursLogic'

export function ProductTourStatusTag({ tour }: { tour: ProductTour }): JSX.Element {
    const status = getProductTourStatus(tour)

    const statusConfig: Record<
        ProgressStatus,
        { label: string; type: 'success' | 'warning' | 'default' | 'completion' }
    > = {
        [ProgressStatus.Draft]: { label: 'Draft', type: 'default' },
        [ProgressStatus.Running]: { label: 'Running', type: 'success' },
        [ProgressStatus.Complete]: { label: 'Complete', type: 'completion' },
    }

    const config = statusConfig[status]
    return <LemonTag type={config.type}>{config.label}</LemonTag>
}

export function ProductToursTable(): JSX.Element {
    const { filteredProductTours, productToursLoading, searchTerm, tab } = useValues(productToursLogic)
    const { deleteProductTour, updateProductTour, setSearchTerm } = useActions(productToursLogic)

    return (
        <>
            <div className={cn('flex flex-wrap gap-2 justify-between mb-0')}>
                <LemonInput
                    type="search"
                    placeholder="Search for product tours"
                    onChange={setSearchTerm}
                    value={searchTerm || ''}
                />
            </div>
            <LemonTable
                dataSource={filteredProductTours}
                defaultSorting={{
                    columnKey: 'created_at',
                    order: -1,
                }}
                rowKey="id"
                nouns={['product tour', 'product tours']}
                data-attr="product-tours-table"
                emptyState={
                    tab === ProductToursTabs.Active
                        ? 'No product tours. Create a new tour to get started!'
                        : 'No archived product tours found'
                }
                loading={productToursLoading}
                columns={[
                    {
                        dataIndex: 'name',
                        title: 'Name',
                        render: function RenderName(_, tour) {
                            return (
                                <div className="flex gap-2 items-center justify-start">
                                    <LemonTag
                                        type="option"
                                        icon={isAnnouncement(tour) ? <IconMegaphone /> : <IconCursorClick />}
                                    >
                                        {isAnnouncement(tour) ? 'Announcement' : 'Tour'}
                                    </LemonTag>
                                    <LemonTableLink
                                        to={urls.productTour(tour.id)}
                                        title={stringWithWBR(tour.name, 17)}
                                    />
                                </div>
                            )
                        },
                    },
                    {
                        title: 'Steps',
                        render: function RenderSteps(_, tour) {
                            return isAnnouncement(tour) ? '-' : (tour.content?.steps?.length ?? 0)
                        },
                    },
                    ...(tab === ProductToursTabs.Active
                        ? [
                              createdAtColumn<ProductTour>() as LemonTableColumn<
                                  ProductTour,
                                  keyof ProductTour | undefined
                              >,
                              {
                                  title: 'Status',
                                  width: 100,
                                  render: function Render(_: any, tour: ProductTour) {
                                      return <ProductTourStatusTag tour={tour} />
                                  },
                              } as LemonTableColumn<ProductTour, keyof ProductTour | undefined>,
                          ]
                        : []),
                    {
                        width: 0,
                        render: function Render(_, tour: ProductTour) {
                            return (
                                <More
                                    overlay={
                                        <>
                                            <LemonButton
                                                fullWidth
                                                onClick={() => router.actions.push(urls.productTour(tour.id))}
                                            >
                                                View
                                            </LemonButton>
                                            {!tour.start_date && (
                                                <LemonButton
                                                    fullWidth
                                                    onClick={() => {
                                                        LemonDialog.open({
                                                            title: 'Launch this product tour?',
                                                            content: (
                                                                <div className="text-sm text-secondary">
                                                                    The tour will immediately start displaying to users
                                                                    matching the display conditions.
                                                                </div>
                                                            ),
                                                            primaryButton: {
                                                                children: 'Launch',
                                                                type: 'primary',
                                                                onClick: () => {
                                                                    updateProductTour({
                                                                        id: tour.id,
                                                                        updatePayload: {
                                                                            start_date: dayjs().toISOString(),
                                                                        },
                                                                    })
                                                                },
                                                                size: 'small',
                                                            },
                                                            secondaryButton: {
                                                                children: 'Cancel',
                                                                type: 'tertiary',
                                                                size: 'small',
                                                            },
                                                        })
                                                    }}
                                                >
                                                    Launch tour
                                                </LemonButton>
                                            )}
                                            {isProductTourRunning(tour) && (
                                                <LemonButton
                                                    fullWidth
                                                    onClick={() => {
                                                        LemonDialog.open({
                                                            title: 'Stop this product tour?',
                                                            content: (
                                                                <div className="text-sm text-secondary">
                                                                    The tour will no longer be visible to your users.
                                                                </div>
                                                            ),
                                                            primaryButton: {
                                                                children: 'Stop',
                                                                type: 'primary',
                                                                onClick: () => {
                                                                    updateProductTour({
                                                                        id: tour.id,
                                                                        updatePayload: {
                                                                            end_date: dayjs().toISOString(),
                                                                        },
                                                                    })
                                                                },
                                                                size: 'small',
                                                            },
                                                            secondaryButton: {
                                                                children: 'Cancel',
                                                                type: 'tertiary',
                                                                size: 'small',
                                                            },
                                                        })
                                                    }}
                                                >
                                                    Stop tour
                                                </LemonButton>
                                            )}
                                            {tour.end_date && !tour.archived && (
                                                <LemonButton
                                                    fullWidth
                                                    onClick={() => {
                                                        LemonDialog.open({
                                                            title: 'Resume this product tour?',
                                                            content: (
                                                                <div className="text-sm text-secondary">
                                                                    Once resumed, the tour will be visible to your users
                                                                    again.
                                                                </div>
                                                            ),
                                                            primaryButton: {
                                                                children: 'Resume',
                                                                type: 'primary',
                                                                onClick: () => {
                                                                    updateProductTour({
                                                                        id: tour.id,
                                                                        updatePayload: {
                                                                            end_date: null,
                                                                        },
                                                                    })
                                                                },
                                                                size: 'small',
                                                            },
                                                            secondaryButton: {
                                                                children: 'Cancel',
                                                                type: 'tertiary',
                                                                size: 'small',
                                                            },
                                                        })
                                                    }}
                                                >
                                                    Resume tour
                                                </LemonButton>
                                            )}
                                            <LemonDivider />
                                            {tour.end_date && tour.archived && (
                                                <LemonButton
                                                    fullWidth
                                                    onClick={() => {
                                                        updateProductTour({
                                                            id: tour.id,
                                                            updatePayload: { archived: false },
                                                        })
                                                    }}
                                                >
                                                    Unarchive
                                                </LemonButton>
                                            )}
                                            {tour.end_date && !tour.archived && (
                                                <LemonButton
                                                    fullWidth
                                                    onClick={() => {
                                                        LemonDialog.open({
                                                            title: 'Archive this product tour?',
                                                            content: (
                                                                <div className="text-sm text-secondary">
                                                                    This action will remove the tour from your active
                                                                    tours list. It can be restored at any time.
                                                                </div>
                                                            ),
                                                            primaryButton: {
                                                                children: 'Archive',
                                                                type: 'primary',
                                                                onClick: () => {
                                                                    updateProductTour({
                                                                        id: tour.id,
                                                                        updatePayload: {
                                                                            archived: true,
                                                                        },
                                                                    })
                                                                },
                                                                size: 'small',
                                                            },
                                                            secondaryButton: {
                                                                children: 'Cancel',
                                                                type: 'tertiary',
                                                                size: 'small',
                                                            },
                                                        })
                                                    }}
                                                >
                                                    Archive
                                                </LemonButton>
                                            )}
                                            <LemonButton
                                                status="danger"
                                                onClick={() => {
                                                    LemonDialog.open({
                                                        title: 'Delete this product tour?',
                                                        content: (
                                                            <div className="text-sm text-secondary">
                                                                This action cannot be undone. All tour data will be
                                                                permanently removed.
                                                            </div>
                                                        ),
                                                        primaryButton: {
                                                            children: 'Delete',
                                                            type: 'primary',
                                                            onClick: () => deleteProductTour(tour.id),
                                                            size: 'small',
                                                        },
                                                        secondaryButton: {
                                                            children: 'Cancel',
                                                            type: 'tertiary',
                                                            size: 'small',
                                                        },
                                                    })
                                                }}
                                                fullWidth
                                            >
                                                Delete
                                            </LemonButton>
                                        </>
                                    }
                                />
                            )
                        },
                    },
                ]}
            />
        </>
    )
}
