import { IconLive } from '@posthog/icons'

import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { hogql } from '~/queries/utils'

import { RuntimeIcon } from 'products/error_tracking/frontend/components/RuntimeIcon'

import { ItemCategory, ItemLoader, ItemRenderer, TimelineItem } from '..'
import { StandardizedPreview } from './base'

export interface ConsoleLogItem extends TimelineItem {
    payload: {
        level: string
        message: string
    }
}

function formatLogLevel(level: string | undefined): string {
    const normalizedLevel = level?.toLowerCase() || 'log'
    return `${normalizedLevel.charAt(0).toUpperCase()}${normalizedLevel.slice(1)}`
}

export const consoleLogRenderer: ItemRenderer<ConsoleLogItem> = {
    sourceIcon: () => <RuntimeIcon runtime="web" />,
    categoryIcon: <IconLive />,
    render: ({ item }): JSX.Element => {
        const levelLabel = formatLogLevel(item.payload.level)

        return <StandardizedPreview primaryText={item.payload.message} secondaryText={levelLabel} />
    },
    renderExpanded: ({ item }): JSX.Element => {
        const levelLabel = formatLogLevel(item.payload.level)

        return (
            <div className="space-y-1">
                <div className="text-xs text-tertiary">Level: {levelLabel}</div>
                <pre className="text-xs whitespace-pre-wrap break-words mb-0">{item.payload.message}</pre>
            </div>
        )
    },
    getMenuItems: ({ item }) =>
        item.payload.message
            ? [
                  {
                      key: 'copy-full-log-text',
                      label: 'Copy full log text',
                      onClick: () => {
                          void copyToClipboard(item.payload.message, 'log text')
                      },
                  },
              ]
            : [],
}

const WINDOW_HOURS = 1

export class ConsoleLogLoader implements ItemLoader<ConsoleLogItem> {
    constructor(
        private readonly sessionId: string,
        private readonly centerTimestamp: Dayjs
    ) {}

    async loadBefore(cursor: Dayjs, limit: number): Promise<{ items: ConsoleLogItem[]; hasMoreBefore: boolean }> {
        const windowStart = this.centerTimestamp.subtract(WINDOW_HOURS, 'hours')
        const query = hogql`SELECT timestamp, level, message FROM log_entries WHERE log_source = 'session_replay' AND log_source_id = ${this.sessionId} AND timestamp >= ${windowStart} AND timestamp < ${cursor} ORDER BY timestamp DESC LIMIT ${limit}`
        const { items, hasMoreBefore } = await this.execute(query, limit, 'before')
        return { items, hasMoreBefore }
    }

    async loadAfter(cursor: Dayjs, limit: number): Promise<{ items: ConsoleLogItem[]; hasMoreAfter: boolean }> {
        const windowEnd = this.centerTimestamp.add(WINDOW_HOURS, 'hours')
        const query = hogql`SELECT timestamp, level, message FROM log_entries WHERE log_source = 'session_replay' AND log_source_id = ${this.sessionId} AND timestamp > ${cursor} AND timestamp <= ${windowEnd} ORDER BY timestamp ASC LIMIT ${limit}`
        const { items, hasMoreAfter } = await this.execute(query, limit, 'after')
        return { items, hasMoreAfter }
    }

    private async execute(
        query: ReturnType<typeof hogql>,
        limit: number,
        direction: 'before' | 'after'
    ): Promise<{ items: ConsoleLogItem[]; hasMoreBefore: boolean; hasMoreAfter: boolean }> {
        const response = await api.queryHogQL(query, { scene: 'ReplaySingle', productKey: 'session_replay' })
        const items = response.results.map(
            (row) =>
                ({
                    id: `log-${String(row[0])}-${String(row[1])}-${String(row[2])}`,
                    category: ItemCategory.CONSOLE_LOGS,
                    timestamp: dayjs.utc(row[0]),
                    payload: {
                        level: row[1],
                        message: row[2],
                    },
                }) as ConsoleLogItem
        )

        const hasMore = items.length === limit

        return direction === 'before'
            ? { items, hasMoreBefore: hasMore, hasMoreAfter: false }
            : { items, hasMoreBefore: false, hasMoreAfter: hasMore }
    }
}
