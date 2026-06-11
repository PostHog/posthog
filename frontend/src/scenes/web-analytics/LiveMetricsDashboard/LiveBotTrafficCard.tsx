import clsx from 'clsx'
import React, { useMemo } from 'react'

import { LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { getSeriesColorPalette } from 'lib/colors'
import { IconRobot } from 'lib/lemon-ui/icons'

import { BotBreakdownItem } from './LiveWebAnalyticsMetricsTypes'

interface LiveBotTrafficCardProps {
    data: BotBreakdownItem[]
    totalBotEvents: number
    totalEvents: number
    isLoading?: boolean
}

const LiveBotTrafficCardInner = ({
    data,
    totalBotEvents,
    totalEvents,
    isLoading,
}: LiveBotTrafficCardProps): JSX.Element => {
    const colors = useMemo(() => getSeriesColorPalette(), [])

    const processedData = useMemo(() => {
        if (data.length === 0) {
            return []
        }
        return [...data]
            .sort((a, b) => {
                if (a.bot === 'Other') {
                    return 1
                }
                if (b.bot === 'Other') {
                    return -1
                }
                return b.count - a.count
            })
            .map((d, index) => ({ item: d, color: colors[index % colors.length] }))
    }, [data, colors])

    const hasData = data.some((d) => d.count > 0)
    const botShare = totalEvents > 0 ? (totalBotEvents / totalEvents) * 100 : 0

    return (
        <div className="bg-bg-light rounded-lg border border-border p-4 h-full min-h-[340px] flex flex-col">
            <div className="mb-4 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-default flex items-center gap-2">
                    <IconRobot className="text-base text-muted" />
                    Bot traffic
                </h3>
                <Tooltip title="Based on PostHog's experimental user agent bot detection, matching search engines, AI crawlers, monitoring tools and more.">
                    <span className="text-xs text-muted">Preview</span>
                </Tooltip>
            </div>

            {isLoading ? (
                <div className="flex-1 flex items-center justify-center">
                    <Spinner className="text-2xl" />
                </div>
            ) : !hasData ? (
                <div className="flex-1 flex items-center justify-center text-muted text-sm text-center px-4">
                    No bots detected in the last 30 minutes. When crawlers like Googlebot, GPTBot or ClaudeBot hit your
                    site, they'll appear here.
                </div>
            ) : (
                <>
                    <div className="text-center mb-4">
                        <div className="text-3xl font-bold tabular-nums">{totalBotEvents.toLocaleString()}</div>
                        <div className="text-xs text-muted">
                            bot events · {botShare.toFixed(botShare < 10 ? 1 : 0)}% of total
                        </div>
                    </div>

                    <div className="space-y-2">
                        {processedData.map(({ item, color }, index) => {
                            const isTop = index === 0
                            return (
                                <Tooltip
                                    key={item.bot}
                                    title={`${item.count.toLocaleString()} events · ${item.bot}${
                                        item.category ? ` (${item.category})` : ''
                                    }`}
                                >
                                    <div className="flex items-center gap-2 cursor-default">
                                        <div
                                            className={clsx(
                                                'text-xs truncate w-20',
                                                isTop ? 'text-default font-medium' : 'text-muted'
                                            )}
                                        >
                                            {item.bot}
                                        </div>
                                        {item.category ? (
                                            <LemonTag type="muted" size="small" className="shrink-0 text-[10px]">
                                                {item.category}
                                            </LemonTag>
                                        ) : null}
                                        <div className="flex-1 h-2 bg-border-light rounded-full overflow-hidden">
                                            <div
                                                className="h-full rounded-full transition-all duration-300 ease-out"
                                                style={{
                                                    width: `${item.percentage}%`,
                                                    backgroundColor: color,
                                                }}
                                            />
                                        </div>
                                        <div
                                            className={clsx(
                                                'w-10 text-xs text-right tabular-nums',
                                                isTop ? 'text-default font-medium' : 'text-muted'
                                            )}
                                        >
                                            {item.percentage.toFixed(0)}%
                                        </div>
                                    </div>
                                </Tooltip>
                            )
                        })}
                    </div>
                </>
            )}
        </div>
    )
}

export const LiveBotTrafficCard = React.memo(LiveBotTrafficCardInner)
