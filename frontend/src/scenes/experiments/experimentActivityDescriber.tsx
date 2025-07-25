import clsx from 'clsx'
import {
    ActivityChange,
    ActivityLogItem,
    HumanizedChange,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import { dayjs } from 'lib/dayjs'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'
import { CONCLUSION_DISPLAY_CONFIG } from 'scenes/experiments/constants'
import { urls } from 'scenes/urls'
import { match } from 'ts-pattern'
import { Experiment, ExperimentConclusion, ProgressStatus } from '~/types'
import { StatusTag } from './ExperimentView/components'

/**
 * if an id is provided, it returns a link to the experiemt. Otherwise, just the name.
 */
const nameOrLinkToExperiment = (name: string | null, id?: string): JSX.Element | string => {
    if (id) {
        return <Link to={urls.experiment(id)}>{name}</Link>
    }
    return name || '(unknown)'
}

/**
 * id an id is provided, it returns a link to the shared metric. Otherwise, just the name.
 */
const nameOrLinkToSharedMetric = (name: string | null, id?: string): JSX.Element | string => {
    if (id) {
        return <Link to={urls.experimentsSharedMetric(id)}>{name}</Link>
    }

    return name || '(unknown)'
}

/**
 * we pick the allowed properties, and shoehorn in deleted because it's missing from the type
 */
type AllowedExperimentFields = Pick<Experiment, 'conclusion' | 'start_date' | 'end_date' | 'metrics'> & {
    deleted: boolean
}

const getSharedMetricChangeMappings = (sharedMetricChange: ActivityChange): string | JSX.Element | null => {
    return match(sharedMetricChange).otherwise(() => null)
}

const getExperimentChangeMappings = (experimentChange: ActivityChange): string | JSX.Element | null => {
    /**
     * a little type assertion to force field into the allowed experiment fields
     */
    return match(experimentChange as ActivityChange & { field: keyof AllowedExperimentFields })
        .with({ field: 'start_date' }, ({ action, before, after }) => {
            /**
             * id start date is created, the experiment has been launched
             */
            if (action === 'created' && before === null && after !== null) {
                return 'launched experiment:'
            }

            /**
             * if start date has changed, we report how much time was added or removed
             */
            if (action === 'changed' && before !== null && after !== null) {
                const beforeDate = dayjs(before as string)
                const afterDate = dayjs(after as string)

                if (beforeDate.isValid() && afterDate.isValid()) {
                    const diff = afterDate.diff(beforeDate, 'minute')
                    const duration = dayjs.duration(Math.abs(diff), 'minute')
                    const sign = diff > 0 ? 'moved the start date forward' : 'moved the start date back'

                    return `${sign} by ${duration.humanize()} on`
                }
            }

            return 'updated the start date of'
        })
        .with({ field: 'end_date' }, ({ action, before, after }) => {
            /**
             * if end date is created, the experiment has been stopped
             */
            if (action === 'created' && before === null && after !== null) {
                return 'stopped experiment'
            }

            return 'updated the end date of'
        })
        .with({ field: 'conclusion' }, ({ action, before, after }) => {
            /**
             * if conclusion was creted, the experiment was closed. This is usually
             * acompanied by the end date creation
             */
            if (action === 'created' && before === null) {
                return (
                    <span>
                        completed it as <ExperimentConclusionTag conclusion={after as ExperimentConclusion} />:
                    </span>
                )
            }

            return null
        })
        .with({ field: 'metrics' }, ({ action, before, after }) => {
            /**
             * if a metric is created, the user has added the first metric to the experiment.
             */
            if (action === 'created' && before === null && after !== null) {
                return 'added the first metric to'
            }

            return null
        })
        .with({ field: 'deleted' }, ({ action, before, after }) => {
            /**
             * if deleted has been changed from false to true, the experiment has been
             * deleted
             */
            if (action === 'changed' && !before && after) {
                return 'deleted experiment:'
            }
            return null
        })
        .otherwise(() => null)
}

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

const ExperimentConclusionTag = ({ conclusion }: { conclusion: ExperimentConclusion }): JSX.Element => (
    <div className="font-semibold inline-flex items-center gap-2">
        <div className={clsx('w-2 h-2 rounded-full', CONCLUSION_DISPLAY_CONFIG[conclusion]?.color || '')} />
        <span>{CONCLUSION_DISPLAY_CONFIG[conclusion]?.title || conclusion}</span>
    </div>
)

export const experimentActivityDescriber = (logItem: ActivityLogItem): HumanizedChange => {
    /**
     * we only have two item types, `shared_metric` or the `null` default for
     * experiments.
     */
    const isSharedMetric = logItem.detail.type === 'shared_metric'

    return match(logItem)
        .with({ activity: 'created' }, () => {
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
                .map((change) => (isSharedMetric ? getSharedMetricChangeMappings : getExperimentChangeMappings)(change))
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
        .with({ activity: 'deleted', detail: { type: 'shared_metric' } }, () => {
            /**
             * experiments have soft deletes, so this applies only to
             * shared metrics
             */
            return {
                description: (
                    <SentenceList
                        listParts={['deleted shared metric:']}
                        prefix={<strong>{userNameForLogItem(logItem)}</strong>}
                        suffix={logItem.detail.name}
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
