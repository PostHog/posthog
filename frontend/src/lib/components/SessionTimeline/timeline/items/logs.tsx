import { ItemCategory, ItemLoaderFactory, ItemRenderer, TimelineItem } from '..'

import { IconTerminal } from '@posthog/icons'

import { Dayjs, dayjs } from 'lib/dayjs'

import { RuntimeIcon } from 'products/error_tracking/frontend/components/RuntimeIcon'

import { BasePreview, LogEntryLoader } from './base'

export interface ConsoleLogItem extends TimelineItem {
    payload: {
        severity: string
        message: string
    }
}

export const consoleLogRenderer: ItemRenderer<ConsoleLogItem> = {
    sourceIcon: ({}) => <RuntimeIcon runtime="web" />,
    categoryIcon: <IconTerminal />,
    render: ({ item }): JSX.Element => {
        return <BasePreview name={`Console ${item.payload.severity}`} description={item.payload.message} />
    },
}

export class ConsoleLogLoader extends LogEntryLoader<ConsoleLogItem> {
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

    buildItem(timestamp: string, severity: string, message: string): ConsoleLogItem {
        return {
            id: timestamp,
            category: ItemCategory.CONSOLE_LOGS,
            timestamp: dayjs.utc(timestamp),
            payload: {
                severity: severity,
                message: JSON.parse(message),
            },
        } as ConsoleLogItem
    }
}

export const consoleLogLoader: ItemLoaderFactory<ConsoleLogItem> = (sessionId: string, timestamp: Dayjs) => {
    const logLoader = new ConsoleLogLoader(sessionId, timestamp)
    return {
        hasPrevious: logLoader.hasPrevious.bind(logLoader),
        previous: logLoader.previous.bind(logLoader),
        hasNext: logLoader.hasNext.bind(logLoader),
        next: logLoader.next.bind(logLoader),
    }
}
