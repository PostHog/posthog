import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { dayjs } from 'lib/dayjs'

import { TaskPullRequestChip } from 'products/tasks/frontend/spaces/TaskPullRequestChip'
import { pullRequestLabel } from 'products/tasks/frontend/spaces/taskPullRequests'

import { todayPreviewCardLogic } from './todayPreviewCardLogic'
import { TodayPreviewFacts } from './TodayPreviewFacts'
import { TodaySessionStatusIcon } from './TodaySessionStatusIcon'
import { todaySpacesLogic } from './todaySpacesLogic'
import { TodayWorkItem, runStatusLabel } from './todayWorkItems'

export function TodaySessionPreview({ item }: { item: TodayWorkItem }): JSX.Element {
    const { spaceNames } = useValues(todaySpacesLogic)
    const { previewOpened } = useActions(todayPreviewCardLogic)

    useEffect(() => {
        previewOpened({ kind: 'session', item })
        // The card keys this component on the row, so this counts one open for each row.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    return (
        <>
            <div className="flex min-w-0 items-start gap-2">
                <span className="mt-0.5 flex size-3.5 shrink-0 items-center justify-center">
                    <TodaySessionStatusIcon item={item} pinned={false} />
                </span>
                <span className="min-w-0 font-semibold text-foreground wrap-anywhere">
                    {item.title || 'Untitled session'}
                </span>
            </div>
            <div className="text-xs text-muted-foreground">
                {runStatusLabel(item.status)}
                {item.timestamp && ` · Active ${dayjs(item.timestamp).fromNow()}`}
            </div>
            {item.lastMessage && (
                <p className="m-0 line-clamp-3 text-xs text-foreground wrap-anywhere">{item.lastMessage}</p>
            )}
            {item.pullRequests.length > 0 && (
                <div className="flex flex-wrap gap-1">
                    {item.pullRequests.map((pullRequest) => (
                        <TaskPullRequestChip
                            key={pullRequest.url}
                            pullRequest={pullRequest}
                            label={pullRequestLabel(pullRequest, item.repository)}
                            dataAttr="today-pr-chip-preview"
                        />
                    ))}
                </div>
            )}
            <TodayPreviewFacts
                facts={[
                    { label: 'Space', value: item.channel ? (spaceNames[item.channel] ?? null) : null },
                    { label: 'Repository', value: item.repository },
                    { label: 'Created by', value: item.createdByName },
                ]}
            />
        </>
    )
}
