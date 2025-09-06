import { ItemCategory, ItemLoader, ItemRenderer, TimelineItem } from '..'

import { IconJavascript, IconTerminal } from '@posthog/icons'
import { pluginEvent } from '@posthog/rrweb-types'

import { dayjs } from 'lib/dayjs'

import { RRWebRecordingConsoleLogPayload, RecordingSnapshot } from '~/types'

import { WithId } from '../../snapshot-loader'
import { BasePreview, SnapshotItemLoader } from './base'

export interface ConsoleLogItem extends TimelineItem {
    payload: {
        level: string
        lines: string[]
        trace: string[]
    }
}

const CONSOLE_LOG_PLUGIN_NAME = 'rrweb/console@1'

function _isPluginSnapshot(x: unknown): x is pluginEvent {
    return (x as pluginEvent).type === 6
}

export class ConsoleLogItemLoader extends SnapshotItemLoader<ConsoleLogItem> implements ItemLoader<ConsoleLogItem> {
    fromSnapshot(snapshot: WithId<RecordingSnapshot>): ConsoleLogItem | null {
        if (!_isPluginSnapshot(snapshot) || !(snapshot.data.plugin === CONSOLE_LOG_PLUGIN_NAME)) {
            return null
        }
        const data = snapshot.data.payload as RRWebRecordingConsoleLogPayload
        const { level, payload, trace } = data
        const lines = (Array.isArray(payload) ? payload : [payload]).filter((x) => !!x) as string[]
        return {
            id: snapshot.id,
            category: ItemCategory.CONSOLE_LOGS,
            timestamp: dayjs.utc(snapshot.timestamp),
            payload: {
                level,
                lines,
                trace,
            },
        }
    }
}

export const consoleLogsRenderer: ItemRenderer<ConsoleLogItem> = {
    sourceIcon: () => <IconJavascript />,
    categoryIcon: <IconTerminal />,
    render: ({ item }): JSX.Element => {
        const content = item.payload.lines.join('\n')
        const level = item.payload.level
        return <BasePreview name={level} description={content} />
    },
}
