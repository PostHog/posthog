import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconInfo } from '@posthog/icons'

import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { replayActiveScreensTableLogic } from 'scenes/session-recordings/components/replayActiveScreensTableLogic'
import { urls } from 'scenes/urls'

import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, ReplayTabs } from '~/types'

export const ReplayActiveScreensTable = (): JSX.Element => {
    const { countedScreens, countedScreensLoading } = useValues(replayActiveScreensTableLogic({ scene: 'templates' }))

    return (
        <div className="flex flex-col border rounded bg-surface-primary w-full px-4 py-2">
            <LemonTable
                embedded={true}
                columns={[
                    {
                        title: (
                            <>
                                <Tooltip title="Click a row to see recordings.">
                                    <div className="flex flex-row gap-2 items-center cursor-pointer">
                                        <IconInfo className="text-xl" /> Last 7 days most active pages
                                    </div>
                                </Tooltip>
                            </>
                        ),
                        dataIndex: 'screen',
                        align: 'left',
                        width: '90%',
                    },
                    { align: 'left', dataIndex: 'count', width: '10%' },
                ]}
                dataSource={countedScreens || []}
                loading={countedScreensLoading}
                onRow={(record) => {
                    return {
                        className: 'cursor-pointer hover:bg-surface-secondary',
                        onClick: () => {
                            router.actions.push(
                                urls.replay(ReplayTabs.Home, {
                                    date_from: '-7d',
                                    filter_group: {
                                        type: FilterLogicalOperator.And,
                                        values: [
                                            {
                                                type: FilterLogicalOperator.And,
                                                values: [
                                                    {
                                                        // Direct $current_url property filter instead of $pageview event filter
                                                        // This matches any event with $current_url property, not just pageviews
                                                        key: '$current_url',
                                                        value: record.screen,
                                                        operator: PropertyOperator.IContains,
                                                        type: PropertyFilterType.Event,
                                                    },
                                                ],
                                            },
                                        ],
                                    },
                                })
                            )
                        },
                    }
                }}
            />
        </div>
    )
}
