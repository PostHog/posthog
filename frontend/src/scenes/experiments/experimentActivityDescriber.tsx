import { ActivityLogItem, HumanizedChange, userNameForLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import { match } from 'ts-pattern'
import { ProgressStatus } from '~/types'
import { StatusTag } from './ExperimentView/components'

function nameOrLinkToExperiment(id: string | undefined, name: string | null): JSX.Element | string {
    if (id) {
        return <Link to={urls.experiment(id)}>{name}</Link>
    }
    return name || '(unknown)'
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
                    {nameOrLinkToExperiment(logItem?.item_id, logItem?.detail.name)}
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
            suffix={nameOrLinkToExperiment(logItem.item_id, logItem.detail.name)}
        />
    )
}

export const experimentActivityDescriber = (logItem: ActivityLogItem): HumanizedChange => {
    //bail for shared metrics
    if (logItem.detail.type === 'shared_metric') {
        return {
            description: null,
        }
    }

    return match(logItem.activity)
        .with('created', () => {
            /**
             * created experiments always have the draft status.
             */
            return {
                description: (
                    <SentenceList
                        prefix={<strong>{userNameForLogItem(logItem)}</strong>}
                        listParts={[
                            <span>
                                created a new <StatusTag status={ProgressStatus.Draft} /> experiment:
                            </span>,
                        ]}
                        suffix={nameOrLinkToExperiment(logItem?.item_id, logItem?.detail.name)}
                    />
                ),
            }
        })
        .with('updated', () => {
            /**
             * the experiment UI only allows for atomic updates of a single property at a time.
             */
            const changes = logItem.detail?.changes || []

            /**
             * if there are no changes, we don't need to describe the update.
             */
            if (changes.length === 0) {
                return {
                    description: (
                        <SentenceList
                            prefix={<strong>{userNameForLogItem(logItem)}</strong>}
                            listParts={['updated']}
                            suffix={nameOrLinkToExperiment(logItem?.item_id, logItem?.detail.name)}
                        />
                    ),
                }
            }

            /**
             * this needs to be refactored to handle multiple changes, for example,
             * when an experiment stops and we set a conclusion.
             */
            const change = changes[0]

            /**
             * if a start date is created, the experiment has been launched.
             */
            if (
                change.action === 'created' &&
                change.field === 'start_date' &&
                change.before === null &&
                change.after !== null
            ) {
                return {
                    description: (
                        <SentenceList
                            prefix={<strong>{userNameForLogItem(logItem)}</strong>}
                            listParts={['launched experiment']}
                            suffix={nameOrLinkToExperiment(logItem?.item_id, logItem?.detail.name)}
                        />
                    ),
                }
            }

            /**
             * if an end date is created, the experiment has been completed.
             */
            if (
                change.action === 'created' &&
                change.field === 'end_date' &&
                change.before === null &&
                change.after !== null
            ) {
                return {
                    description: (
                        <SentenceList
                            prefix={<strong>{userNameForLogItem(logItem)}</strong>}
                            listParts={['stopped experiment']}
                            suffix={nameOrLinkToExperiment(logItem?.item_id, logItem?.detail.name)}
                        />
                    ),
                }
            }

            /**
             * if a metric is created, the user has added the first metric to the experiment.
             */
            if (
                change.action === 'created' &&
                change.field === 'metrics' &&
                change.before === null &&
                change.after !== null
            ) {
                return {
                    description: (
                        <SentenceList
                            prefix={<strong>{userNameForLogItem(logItem)}</strong>}
                            listParts={['added the first metric to']}
                            suffix={nameOrLinkToExperiment(logItem?.item_id, logItem?.detail.name)}
                        />
                    ),
                }
            }

            /**
             * soft deletes
             */
            if (change.action === 'changed' && change.field === 'deleted' && !change.before && change.after) {
                return {
                    description: (
                        <SentenceList
                            prefix={<strong>{userNameForLogItem(logItem)}</strong>}
                            listParts={['deleted experiment']}
                            suffix={nameOrLinkToExperiment(logItem?.item_id, logItem?.detail.name)}
                        />
                    ),
                }
            }

            /**
             * TODO: return null for now, until we cover all existing uses.
             */
            return {
                description: null,
            }
        })
        .with('deleted', () => {
            /**
             * today we do soft deletes, so we keep this for future proofing
             */
            return {
                description: (
                    <SentenceList
                        listParts={['deleted experiment']}
                        prefix={<strong>{userNameForLogItem(logItem)}</strong>}
                        suffix={logItem?.detail.name}
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
