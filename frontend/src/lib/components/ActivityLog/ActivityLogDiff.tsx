import { ActivityLogChangeDiff } from './ActivityLogChangeDiff'
import { HumanizedActivityLogItem } from './humanizeActivity'

export const ActivityLogDiff = ({ logItem }: { logItem: HumanizedActivityLogItem }): JSX.Element => {
    const changes = logItem.unprocessed?.detail.changes

    return (
        <div className="flex flex-col deprecated-space-y-2 px-2 py-1">
            <div className="flex flex-col deprecated-space-y-2">
                {changes?.length ? (
                    changes.map((change, i) => {
                        return (
                            <ActivityLogChangeDiff
                                key={i}
                                field={change.field}
                                before={change.before}
                                after={change.after}
                            />
                        )
                    })
                ) : (
                    <div className="text-secondary">This item has no changes to compare</div>
                )}
            </div>
        </div>
    )
}
