import { match } from 'ts-pattern'

import { ActivityLogItem, HumanizedChange, userNameForLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import { LemonCard } from 'lib/lemon-ui/LemonCard'

import { ExperimentStatus } from '~/types'

import {
    getExperimentChangeDescription,
    getHoldoutChangeDescription,
    getSharedMetricChangeDescription,
    nameOrLinkToExperiment,
    nameOrLinkToSharedMetric,
} from './activity-descriptions'
import { StatusTag } from './ExperimentView/components'

//exporting so the linter doesn't complain about this not being used
export const ExperimentDetails = ({
    logItem,
    status,
}: {
    logItem: ActivityLogItem
    status: ExperimentStatus
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
            prefix={<strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>}
            listParts={['performed an unknown action on']}
            suffix={nameOrLinkToExperiment(logItem.detail.name, logItem.item_id)}
        />
    )
}

// Recursively pull plain text out of a string / JSX node so getPreposition can
// inspect its keywords. The conclusion matcher returns JSX whose leading verb
// ("changed") would otherwise be invisible to the keyword check.
const extractText = (node: string | JSX.Element | null | undefined): string => {
    if (node === null || node === undefined || typeof node === 'boolean') {
        return ''
    }
    if (typeof node === 'string' || typeof node === 'number') {
        return String(node)
    }
    if (Array.isArray(node)) {
        return node.map(extractText).join(' ')
    }
    const children = (node as JSX.Element).props?.children
    return children !== undefined ? extractText(children) : ''
}

// Helper to determine the right preposition based on the action text
const getPreposition = (item: string | JSX.Element): string => {
    const text = extractText(item)
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

// Flatten the result of getExperimentChangeDescription into the parts that
// SentenceList will join. Prepositions are NOT appended here — the outer
// updated branch attaches a single preposition to the last list part so the
// joined sentence reads naturally (e.g. "changed A, changed B, and changed C
// for Experiment Name").
const humanizeExperimentChange = (
    result: string | JSX.Element | (string | JSX.Element)[] | null
): (string | JSX.Element)[] => {
    if (result === null) {
        return []
    }
    if (Array.isArray(result)) {
        return result.filter(Boolean) as (string | JSX.Element)[]
    }
    return [result]
}

const appendPreposition = (item: string | JSX.Element): string | JSX.Element => {
    const preposition = getPreposition(item)
    return typeof item === 'string' ? (
        `${item} ${preposition}`
    ) : (
        <span>
            {item} {preposition}
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
                        prefix={<strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>}
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
                        prefix={<strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>}
                        listParts={[
                            isSharedMetric ? (
                                <span>created a new shared metric:</span>
                            ) : (
                                <span>
                                    created a new <StatusTag status={ExperimentStatus.Draft} /> experiment:
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
                        prefix={<strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>}
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
                        prefix={<strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>}
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
                        prefix={<strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>}
                        listParts={['deleted experiment holdout:']}
                        suffix={<strong>{logItem.detail.name}</strong>}
                    />
                ),
            }
        })
        .with({ activity: 'deleted' }, ({ item_id, detail }) => {
            return {
                description: (
                    <SentenceList
                        prefix={<strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>}
                        listParts={['deleted experiment:']}
                        suffix={nameOrLinkToExperiment(detail.name, item_id)}
                    />
                ),
            }
        })
        .with({ activity: 'restored' }, ({ item_id, detail }) => {
            return {
                description: (
                    <SentenceList
                        prefix={<strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>}
                        listParts={['restored experiment:']}
                        suffix={nameOrLinkToExperiment(detail.name, item_id)}
                    />
                ),
            }
        })
        .with({ activity: 'updated' }, ({ item_id, detail: updateLogDetail }) => {
            /**
             * This is the catch all for all experiment updates
             */
            const changes = updateLogDetail.changes || []

            const isExperiment = updateLogDetail.type !== 'shared_metric' && updateLogDetail.type !== 'holdout'

            let listParts: (string | JSX.Element)[]
            if (changes.length === 0) {
                listParts = ['updated']
            } else if (isExperiment) {
                // Flatten each change into one or more parts. The preposition is appended
                // exactly once below — to the final part — so the SentenceList reads
                // "changed A, changed B, and changed C for Experiment Name" instead of
                // duplicating prepositions inside each clause.
                listParts = changes.flatMap((change) =>
                    humanizeExperimentChange(getExperimentChangeDescription(change))
                )
            } else {
                listParts = changes
                    .map((change) =>
                        match(updateLogDetail.type)
                            .with('shared_metric', () => getSharedMetricChangeDescription(change))
                            .with('holdout', () => getHoldoutChangeDescription(change))
                            .otherwise(() => null)
                    )
                    .filter((part): part is string | JSX.Element => part !== null)
            }

            if (isExperiment && changes.length > 0 && listParts.length > 0) {
                const lastIndex = listParts.length - 1
                listParts[lastIndex] = appendPreposition(listParts[lastIndex])
            }

            const suffix = match(updateLogDetail.type)
                .with('shared_metric', () => nameOrLinkToSharedMetric(updateLogDetail.name, item_id))
                .with('holdout', () => <strong>{updateLogDetail.name}</strong>)
                .otherwise(() => nameOrLinkToExperiment(updateLogDetail.name, item_id))

            return {
                description: (
                    <SentenceList
                        prefix={<strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>}
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
