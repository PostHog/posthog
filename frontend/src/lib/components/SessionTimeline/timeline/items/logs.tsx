import { ItemCategory, ItemRenderer, TimelineItem } from '..'

import { IconTerminal } from '@posthog/icons'

import { Dayjs } from 'lib/dayjs'
import { uuid } from 'lib/utils'

import { RuntimeIcon } from 'products/error_tracking/frontend/components/RuntimeIcon'

import { BasePreview, LogEntryLoader } from './base'

export interface ConsoleLogItem extends TimelineItem {
    payload: {
        level: string
        message: string
    }
}

export const consoleLogRenderer: ItemRenderer<ConsoleLogItem> = {
    sourceIcon: ({}) => <RuntimeIcon runtime="web" />,
    categoryIcon: <IconTerminal />,
    render: ({ item }): JSX.Element => {
        return (
            <BasePreview
                name={`Console ${item.payload.level}`}
                description={item.payload.message}
                descriptionTitle={item.payload.message}
            />
        )
    },
}

export class ConsoleLogItemLoader extends LogEntryLoader<ConsoleLogItem> {
    sessionId: string

    constructor(sessionId: string, timestamp: Dayjs) {
        super(timestamp)
        this.sessionId = sessionId
    }

    logSource(): string {
        return 'session_replay'
    }

    logSourceId(): string {
        return this.sessionId
    }

    buildItem({
        timestamp,
        level,
        message,
    }: {
        timestamp: Dayjs
        level: 'info' | 'warn' | 'error'
        message: string
    }): ConsoleLogItem {
        return {
            id: uuid(),
            category: ItemCategory.CONSOLE_LOGS,
            timestamp,
            payload: {
                level,
                message,
            },
        } as ConsoleLogItem
    }
}
