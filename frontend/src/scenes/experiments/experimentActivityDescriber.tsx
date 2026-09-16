import { match } from 'ts-pattern'

import {
    ActivityLogItem,
    ActivityLogUserName,
    HumanizedChange,
    activityLogSummary,
} from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'

import { ExperimentStatus } from '~/types'

import { StatusTag } from 'products/experiments/frontend/components/StatusTag'

import {
    getExperimentChangeDescription,
    getHoldoutChangeDescription,
    getSharedMetricChangeDescription,
    nameOrLinkToExperiment,
    nameOrLinkToSharedMetric,
} from './activity-descriptions'

const UnknownAction = ({ logItem }: { logItem: ActivityLogItem }): JSX.Element => {
    return (
        <SentenceList
            prefix={<ActivityLogUserName logItem={logItem} />}
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
    // A part that ends with a colon already introduces the experiment name.
    if (extractText(item).trimEnd().endsWith(':')) {
        return item
    }
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
     * Item types: `shared_metric`, `saved_metric_config`, `holdout`, or the `null` default for experiments.
     */
    const isSharedMetric = logItem.detail.type === 'shared_metric'

    return match(logItem)
        .with({ activity: 'created', detail: { type: 'saved_metric_config' } }, () => {
            return {
                summary: activityLogSummary(
                    logItem,
                    'Added a shared metric',
                    <>
                        {logItem.detail.name} to {nameOrLinkToExperiment('experiment', logItem.item_id)}
                    </>
                ),
                description: (
                    <SentenceList
                        prefix={<ActivityLogUserName logItem={logItem} />}
                        listParts={['added shared metric']}
                        suffix={
                            <span>
                                <strong>{logItem.detail.name}</strong> to{' '}
                                {nameOrLinkToExperiment('experiment', logItem.item_id)}
                            </span>
                        }
                    />
                ),
            }
        })
        .with({ activity: 'updated', detail: { type: 'saved_metric_config' } }, () => {
            return {
                summary: activityLogSummary(
                    logItem,
                    'Updated the shared metric configuration',
                    <>
                        {logItem.detail.name} on {nameOrLinkToExperiment('experiment', logItem.item_id)}
                    </>
                ),
                description: (
                    <SentenceList
                        prefix={<ActivityLogUserName logItem={logItem} />}
                        listParts={['updated configuration for shared metric']}
                        suffix={
                            <span>
                                <strong>{logItem.detail.name}</strong> on{' '}
                                {nameOrLinkToExperiment('experiment', logItem.item_id)}
                            </span>
                        }
                    />
                ),
            }
        })
        .with({ activity: 'created', detail: { type: 'holdout' } }, () => {
            return {
                summary: activityLogSummary(logItem, 'Created an experiment holdout', logItem.detail.name || 'Holdout'),
                description: (
                    <SentenceList
                        prefix={<ActivityLogUserName logItem={logItem} />}
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
                summary: activityLogSummary(
                    logItem,
                    isSharedMetric ? (
                        'Created a shared metric'
                    ) : (
                        <>
                            Created a <StatusTag status={ExperimentStatus.Draft} /> experiment
                        </>
                    ),
                    (isSharedMetric ? nameOrLinkToSharedMetric : nameOrLinkToExperiment)(
                        logItem.detail.name,
                        logItem.item_id
                    )
                ),
                description: (
                    <SentenceList
                        prefix={<ActivityLogUserName logItem={logItem} />}
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
                summary: activityLogSummary(logItem, 'Deleted the experiment', logItem.detail.name || 'Experiment'),
                description: (
                    <SentenceList
                        prefix={<ActivityLogUserName logItem={logItem} />}
                        listParts={['deleted experiment:']}
                        suffix={logItem.detail.name}
                    />
                ),
            }
        })
        .with({ activity: 'deleted', detail: { type: 'saved_metric_config' } }, () => {
            return {
                summary: activityLogSummary(
                    logItem,
                    'Removed the shared metric',
                    <>
                        {logItem.detail.name} from {nameOrLinkToExperiment('experiment', logItem.item_id)}
                    </>
                ),
                description: (
                    <SentenceList
                        prefix={<ActivityLogUserName logItem={logItem} />}
                        listParts={['removed shared metric']}
                        suffix={
                            <span>
                                <strong>{logItem.detail.name}</strong> from{' '}
                                {nameOrLinkToExperiment('experiment', logItem.item_id)}
                            </span>
                        }
                    />
                ),
            }
        })
        .with({ activity: 'deleted', detail: { type: 'shared_metric' } }, () => {
            /**
             * Shared metrics are not soft deleted.
             */
            return {
                summary: activityLogSummary(
                    logItem,
                    'Deleted the shared metric',
                    logItem.detail.name || 'Shared metric'
                ),
                description: (
                    <SentenceList
                        prefix={<ActivityLogUserName logItem={logItem} />}
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
                summary: activityLogSummary(
                    logItem,
                    'Deleted the experiment holdout',
                    logItem.detail.name || 'Holdout'
                ),
                description: (
                    <SentenceList
                        prefix={<ActivityLogUserName logItem={logItem} />}
                        listParts={['deleted experiment holdout:']}
                        suffix={<strong>{logItem.detail.name}</strong>}
                    />
                ),
            }
        })
        .with({ activity: 'deleted' }, ({ item_id, detail }) => {
            return {
                summary: activityLogSummary(
                    logItem,
                    'Deleted the experiment',
                    nameOrLinkToExperiment(detail.name, item_id)
                ),
                description: (
                    <SentenceList
                        prefix={<ActivityLogUserName logItem={logItem} />}
                        listParts={['deleted experiment:']}
                        suffix={nameOrLinkToExperiment(detail.name, item_id)}
                    />
                ),
            }
        })
        .with({ activity: 'restored' }, ({ item_id, detail }) => {
            return {
                summary: activityLogSummary(
                    logItem,
                    'Restored the experiment',
                    nameOrLinkToExperiment(detail.name, item_id)
                ),
                description: (
                    <SentenceList
                        prefix={<ActivityLogUserName logItem={logItem} />}
                        listParts={['restored experiment:']}
                        suffix={nameOrLinkToExperiment(detail.name, item_id)}
                    />
                ),
            }
        })
        .with({ activity: 'paused' }, ({ item_id, detail }) => {
            return {
                summary: activityLogSummary(
                    logItem,
                    'Paused the experiment',
                    nameOrLinkToExperiment(detail.name, item_id)
                ),
                description: (
                    <SentenceList
                        prefix={<ActivityLogUserName logItem={logItem} />}
                        listParts={['paused experiment:']}
                        suffix={nameOrLinkToExperiment(detail.name, item_id)}
                    />
                ),
            }
        })
        .with({ activity: 'resumed' }, ({ item_id, detail }) => {
            return {
                summary: activityLogSummary(
                    logItem,
                    'Resumed the experiment',
                    nameOrLinkToExperiment(detail.name, item_id)
                ),
                description: (
                    <SentenceList
                        prefix={<ActivityLogUserName logItem={logItem} />}
                        listParts={['resumed experiment:']}
                        suffix={nameOrLinkToExperiment(detail.name, item_id)}
                    />
                ),
            }
        })
        .with({ activity: 'reset' }, ({ item_id, detail }) => {
            return {
                summary: activityLogSummary(
                    logItem,
                    'Reset the experiment',
                    nameOrLinkToExperiment(detail.name, item_id)
                ),
                description: (
                    <SentenceList
                        prefix={<ActivityLogUserName logItem={logItem} />}
                        listParts={['reset experiment:']}
                        suffix={nameOrLinkToExperiment(detail.name, item_id)}
                    />
                ),
            }
        })
        .with({ activity: 'variant_shipped' }, ({ item_id, detail }) => {
            const variantKey = detail.changes?.find((change) => change.field === 'shipped_variant')?.after
            return {
                summary: activityLogSummary(
                    logItem,
                    typeof variantKey === 'string' ? <>Shipped variant {variantKey}</> : 'Shipped a variant',
                    nameOrLinkToExperiment(detail.name, item_id)
                ),
                description: (
                    <SentenceList
                        prefix={<ActivityLogUserName logItem={logItem} />}
                        listParts={[
                            typeof variantKey === 'string' ? (
                                <span>
                                    shipped variant <strong>{variantKey}</strong> for
                                </span>
                            ) : (
                                'shipped a variant for'
                            ),
                        ]}
                        suffix={nameOrLinkToExperiment(detail.name, item_id)}
                    />
                ),
            }
        })
        .with({ activity: 'exposure_frozen' }, ({ item_id, detail }) => {
            return {
                summary: activityLogSummary(logItem, 'Froze exposure', nameOrLinkToExperiment(detail.name, item_id)),
                description: (
                    <SentenceList
                        prefix={<ActivityLogUserName logItem={logItem} />}
                        listParts={['froze exposure for']}
                        suffix={nameOrLinkToExperiment(detail.name, item_id)}
                    />
                ),
            }
        })
        .with({ activity: 'exposure_unfrozen' }, ({ item_id, detail }) => {
            return {
                summary: activityLogSummary(logItem, 'Unfroze exposure', nameOrLinkToExperiment(detail.name, item_id)),
                description: (
                    <SentenceList
                        prefix={<ActivityLogUserName logItem={logItem} />}
                        listParts={['unfroze exposure for']}
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

            const isExperiment =
                updateLogDetail.type !== 'shared_metric' &&
                updateLogDetail.type !== 'holdout' &&
                updateLogDetail.type !== 'saved_metric_config'

            const conclusionCommentChange = isExperiment
                ? changes.find((change) => change.field === 'conclusion_comment')
                : undefined
            const conclusionComment =
                typeof conclusionCommentChange?.after === 'string' && conclusionCommentChange.after.trim()
                    ? conclusionCommentChange.after
                    : undefined
            const conclusionCommentRemoved =
                !conclusionComment &&
                typeof conclusionCommentChange?.before === 'string' &&
                Boolean(conclusionCommentChange.before.trim())

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

            if (isExperiment && changes.length > 0 && listParts.length === 0) {
                if (conclusionComment) {
                    // A comment-only edit still gets a row; the comment renders below it.
                    listParts = ['changed the conclusion']
                } else if (conclusionCommentRemoved) {
                    listParts = ['removed the conclusion comment']
                } else {
                    // humanize() skips log items with a null description
                    return { description: null }
                }
            }

            const summaryParts = [...listParts]

            if (isExperiment && changes.length > 0 && listParts.length > 0) {
                const lastIndex = listParts.length - 1
                listParts[lastIndex] = appendPreposition(listParts[lastIndex])
            }

            const suffix = match(updateLogDetail.type)
                .with('shared_metric', () => nameOrLinkToSharedMetric(updateLogDetail.name, item_id))
                .with('holdout', () => <strong>{updateLogDetail.name}</strong>)
                .otherwise(() => nameOrLinkToExperiment(updateLogDetail.name, item_id))

            return {
                summary: activityLogSummary(
                    logItem,
                    <SentenceList listParts={summaryParts.length ? summaryParts : ['Updated']} />,
                    suffix
                ),
                description: (
                    <SentenceList
                        prefix={<ActivityLogUserName logItem={logItem} />}
                        listParts={listParts}
                        suffix={suffix}
                    />
                ),
                extendedDescription: conclusionComment ? (
                    <blockquote className="border-l-2 pl-2 text-secondary">{conclusionComment}</blockquote>
                ) : undefined,
            }
        })
        .otherwise(() => {
            return {
                summary: activityLogSummary(
                    logItem,
                    'Performed an unknown action',
                    nameOrLinkToExperiment(logItem.detail.name, logItem.item_id)
                ),
                description: <UnknownAction logItem={logItem} />,
            }
        })
}
