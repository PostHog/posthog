import { ActivityLogItem, HumanizedChange, userNameForLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { match } from 'ts-pattern'
import { ProgressStatus } from '~/types'
import {
    getExperimentChangeDescription,
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

export const experimentActivityDescriber = (logItem: ActivityLogItem): HumanizedChange => {
    /**
     * we only have two item types, `shared_metric` or the `null` default for
     * experiments.
     */
    const isSharedMetric = logItem.detail.type === 'shared_metric'

    return match(logItem)
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
        .with({ activity: 'updated' }, () => {
            const changes = logItem.detail.changes || []
            /**
             * if there are no changes, we don't need to describe the update.
             */
            if (changes.length === 0) {
                return {
                    description: (
                        <SentenceList
                            prefix={<strong>{userNameForLogItem(logItem)}</strong>}
                            listParts={['updated']}
                            suffix={(isSharedMetric ? nameOrLinkToSharedMetric : nameOrLinkToExperiment)(
                                logItem.detail.name,
                                logItem.item_id
                            )}
                        />
                    ),
                }
            }

            const listParts = changes
                .map((change) =>
                    (isSharedMetric ? getSharedMetricChangeDescription : getExperimentChangeDescription)(change)
                )
                .filter((part) => part !== null)

            if (listParts.length === 0) {
                return { description: null }
            }

            /**
             * we always prefix with the user name, and suffix with a link to the resource
             */
            return {
                description: (
                    <SentenceList
                        prefix={<strong>{userNameForLogItem(logItem)}</strong>}
                        listParts={listParts}
                        suffix={(isSharedMetric ? nameOrLinkToSharedMetric : nameOrLinkToExperiment)(
                            logItem.detail.name,
                            logItem.item_id
                        )}
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
