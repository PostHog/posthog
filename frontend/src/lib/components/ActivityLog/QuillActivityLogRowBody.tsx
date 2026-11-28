import clsx from 'clsx'

import { TZLabel } from 'lib/components/TZLabel'

import { ActivityClientTag } from './ActivityClientTag'
import { ActivityLogDescription } from './ActivityLogDescription'
import { AgentAttribution } from './AgentAttribution'
import { HumanizedActivityLogItem } from './humanizeActivity'

/** The actor, time, summary and attribution of a quill activity row. */
export function QuillActivityLogRowBody({
    logItem,
    expanded,
}: {
    logItem: HumanizedActivityLogItem
    expanded: boolean
}): JSX.Element {
    const heading = (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
            {logItem.summary?.actor}
            {logItem.client && <ActivityClientTag client={logItem.client} />}
            <span className="text-muted-foreground">
                <TZLabel time={logItem.created_at} />
            </span>
        </div>
    )

    // Long resource names have no spaces to break on, so they wrap anywhere to fit the panel.
    return (
        <div className="flex min-w-0 flex-1 flex-col gap-1 [overflow-wrap:anywhere]">
            {logItem.summary ? (
                <>
                    {heading}
                    <div
                        className={clsx(
                            'font-semibold first-letter:uppercase',
                            !expanded && 'line-clamp-2 focus-within:line-clamp-none'
                        )}
                    >
                        {logItem.summary.action}
                    </div>
                    <div className="text-muted-foreground">{logItem.summary.target}</div>
                    {logItem.summary.preview && (
                        <div className={clsx('text-muted-foreground', !expanded && 'line-clamp-2')}>
                            {logItem.summary.preview}
                        </div>
                    )}
                </>
            ) : (
                <div>
                    <ActivityLogDescription logItem={logItem} />
                </div>
            )}
            {logItem.extendedDescription && <div>{logItem.extendedDescription}</div>}
            <div className="empty:hidden">
                <AgentAttribution logItem={logItem} truncateIntent={!expanded} />
            </div>
            {!logItem.summary && heading}
        </div>
    )
}
