import { match } from 'ts-pattern'

import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import { ActivityLogItem, HumanizedChange, userNameForLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { LemonCard } from 'lib/lemon-ui/LemonCard'

import { ProgressStatus } from '~/types'

import { StatusTag } from './ExperimentView/components'
import {
    getExperimentChangeDescription,
    getHoldoutChangeDescription,
    getSharedMetricChangeDescription,
    nameOrLinkToExperiment,
    nameOrLinkToSharedMetric,
} from './activity-descriptions'

//exporting so the linter doesn't complain about this not being used
export const ExperimentDetails = ({
    logItem,
    status,
}: {
    logItem: ActivityLogItem
    status: ProgressStatus
}): JSX.Element => {
    return (
        <LemonCard className="flex items-center justify-between gap-3 p-4">
            <div className="flex flex-col gap-1">
                <strong className="text-sm font-semibold">
                    {nameOrLinkToExperiment(logItem.detail.name, logItem.item_id)}
                </strong>
                <span className="text-xs text-muted">Experiment</span>
            </div>
            <StatusTag status={status} />
        </LemonCard>
    )
}

const UnknownAction = ({ logItem }: { logItem: ActivityLogItem }): JSX.Element => {
    return (
        <SentenceList
            prefix={<strong>{userNameForLogItem(logItem)}</strong>}
            listParts={['performed an unknown action on']}
            suffix={nameOrLinkToExperiment(logItem.detail.name, logItem.item_id)}
        />
    )
}

// Helper to determine the right preposition based on the action text
const getPreposition = (text: string): string => {
    if (text.includes('added') || text.includes('set')) {
        return 'to'
    }

    if (text.includes('removed')) {
        return 'from'
    }

    if (text.includes('changed') || text.includes('returned')) {
        return 'for'
    }

    return 'on'
}

/**
 * Formats the result from getExperimentChangeDescription into a human-readable string
 * Handles arrays by joining with commas and "and" for the last item
 * Adds appropriate preposition (to/for/on) based on the action
 */
const humanizeExperimentChange = (
    result: string | JSX.Element | (string | JSX.Element)[] | null
): string | JSX.Element | null => {
    if (result === null) {
        return null
    }

    if (Array.isArray(result)) {
        // Filter out null/undefined values
        const validItems = result.filter(Boolean)

        if (validItems.length === 0) {
            return null
        }

        if (validItems.length === 1) {
            const item = validItems[0]
            const itemText = typeof item === 'string' ? item : ''
            const preposition = getPreposition(itemText)
            return (
                <span>
                    {item} {preposition}
                </span>
            )
        }

        // Join with commas and "and" for the last item
        const lastItem = validItems[validItems.length - 1]
        const otherItems = validItems.slice(0, -1)

        // Determine preposition based on first item (they should all be similar actions)
        const firstItemText = typeof otherItems[0] === 'string' ? otherItems[0] : ''
        const preposition = getPreposition(firstItemText)

        // If all items are strings, return a string
        const allStrings = validItems.every((item) => typeof item === 'string')
        if (allStrings) {
            return `${otherItems.join(', ')} and ${lastItem} ${preposition}`
        }

        // If mixed or JSX elements, return a span
        return (
            <span>
                {otherItems.map((item, index) => (
                    <span key={index}>
                        {item}
                        {index < otherItems.length - 1 ? ', ' : ' and '}
                    </span>
                ))}
                {lastItem} {preposition}
            </span>
        )
    }

    // Single string or JSX element
    const itemText = typeof result === 'string' ? result : ''
    const preposition = getPreposition(itemText)

    if (typeof result === 'string') {
        return `${result} ${preposition}`
    }

    return (
        <span>
            {result} {preposition}
        </span>
    )
}

export const experimentActivityDescriber = (logItem: ActivityLogItem): HumanizedChange => {
    /**
     * we only have two item types, `shared_metric` or the `null` default for
     * experiments.
     */
    const isSharedMetric = logItem.detail.type === 'shared_metric'

    return match(logItem)
        .with({ activity: 'created', detail: { type: 'holdout' } }, () => {
            return {
                description: (
                    <SentenceList
                        prefix={<strong>{userNameForLogItem(logItem)}</strong>}
                        listParts={['created a new experiment holdout:']}
                        suffix={<strong>{logItem.detail.name}</strong>}
                    />
                ),
            }
        })
        .with({ activity: 'created' }, () => {
            /**
             * we handle both experiments and shared metrics creation here.
             */
            return {
                description: (
                    <SentenceList
                        prefix={<strong>{userNameForLogItem(logItem)}</strong>}
                        listParts={[
                            isSharedMetric ? (
                                <span>created a new shared metric:</span>
                            ) : (
                                <span>
                                    created a new <StatusTag status={ProgressStatus.Draft} /> experiment:
                                </span>
                            ),
                        ]}
                        suffix={(isSharedMetric ? nameOrLinkToSharedMetric : nameOrLinkToExperiment)(
                            logItem.detail.name,
                            logItem.item_id
                        )}
                    />
                ),
            }
        })
        .with({ activity: 'updated', detail: { changes: [{ field: 'deleted', before: false, after: true }] } }, () => {
            /**
             * Experiment deletion is a spacial case of `updated`. If `deleted` has been changed
             * from false to true, the experiment has been deleted.
             */
            return {
                description: (
                    <SentenceList
                        prefix={<strong>{userNameForLogItem(logItem)}</strong>}
                        listParts={['deleted experiment:']}
                        suffix={logItem.detail.name}
                    />
                ),
            }
        })
        .with({ activity: 'deleted', detail: { type: 'shared_metric' } }, () => {
            /**
             * Shared metrics are not soft deleted.
             */
            return {
                description: (
                    <SentenceList
                        prefix={<strong>{userNameForLogItem(logItem)}</strong>}
                        listParts={['deleted shared metric:']}
                        suffix={logItem.detail.name}
                    />
                ),
            }
        })
        .with({ activity: 'deleted', detail: { type: 'holdout' } }, () => {
            /**
             * Holdouts are not soft deleted.
             */
            return {
                description: (
                    <SentenceList
                        prefix={<strong>{userNameForLogItem(logItem)}</strong>}
                        listParts={['deleted experiment holdout:']}
                        suffix={<strong>{logItem.detail.name}</strong>}
                    />
                ),
            }
        })
        .with({ activity: 'updated' }, ({ item_id, detail: updateLogDetail }) => {
            const changes = updateLogDetail.changes || []

            const listParts =
                changes.length === 0
                    ? ['updated']
                    : changes
                          .map((change) =>
                              match(updateLogDetail.type)
                                  .with('shared_metric', () => getSharedMetricChangeDescription(change))
                                  .with('holdout', () => getHoldoutChangeDescription(change))
                                  .otherwise(() => humanizeExperimentChange(getExperimentChangeDescription(change)))
                          )
                          .filter((part) => part !== null)

            if (changes.length > 0 && listParts.length === 0) {
                return { description: null }
            }

            const suffix = match(updateLogDetail.type)
                .with('shared_metric', () => nameOrLinkToSharedMetric(updateLogDetail.name, item_id))
                .with('holdout', () => <strong>{updateLogDetail.name}</strong>)
                .otherwise(() => nameOrLinkToExperiment(updateLogDetail.name, item_id))

            return {
                description: (
                    <SentenceList
                        prefix={<strong>{userNameForLogItem(logItem)}</strong>}
                        listParts={listParts}
                        suffix={suffix}
                    />
                ),
            }
        })
        .otherwise(() => {
            return {
                description: <UnknownAction logItem={logItem} />,
            }
        })
}
