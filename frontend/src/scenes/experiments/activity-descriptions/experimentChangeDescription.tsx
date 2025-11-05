import clsx from 'clsx'
import equal from 'fast-deep-equal'
import { match } from 'ts-pattern'

import { ActivityChange } from 'lib/components/ActivityLog/humanizeActivity'
import { dayjs } from 'lib/dayjs'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { CONCLUSION_DISPLAY_CONFIG } from 'scenes/experiments/constants'
import { getExposureConfigDisplayName } from 'scenes/experiments/utils'
import { urls } from 'scenes/urls'

import type { ExperimentExposureCriteria, ExperimentMetric } from '~/queries/schema/schema-general'
import { Experiment, ExperimentConclusion } from '~/types'

import { getMetricChanges } from './metricChangeDescriptions'

const ExperimentConclusionTag = ({ conclusion }: { conclusion: ExperimentConclusion }): JSX.Element => (
    <div className="font-semibold inline-flex items-center gap-2">
        <div className={clsx('w-2 h-2 rounded-full', CONCLUSION_DISPLAY_CONFIG[conclusion]?.color || '')} />
        <span>{CONCLUSION_DISPLAY_CONFIG[conclusion]?.title || conclusion}</span>
    </div>
)

/**
 * if an id is provided, it returns a link to the experiemt. Otherwise, just the name.
 */
export const nameOrLinkToExperiment = (name: string | null, id?: string): JSX.Element | string => {
    if (id) {
        return <Link to={urls.experiment(id)}>{name}</Link>
    }
    return name || '(unknown)'
}

/**
 * we pick the allowed properties, and shoehorn in deleted because it's missing from the type
 */
type AllowedExperimentFields = Pick<
    Experiment,
    'conclusion' | 'start_date' | 'end_date' | 'metrics' | 'metrics_secondary' | 'exposure_criteria'
> & {
    deleted: boolean
}

export const getExperimentChangeDescription = (
    experimentChange: ActivityChange
): string | JSX.Element | (string | JSX.Element)[] | null => {
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
        .with({ field: 'metrics', action: 'created', before: null }, () => 'added the first metric to')
        .with({ field: 'metrics', action: 'changed' }, ({ before, after }) =>
            getMetricChanges(before as ExperimentMetric[], after as ExperimentMetric[])
        )
        .with({ field: 'metrics_secondary', action: 'changed' }, ({ before, after }) =>
            getMetricChanges(before as ExperimentMetric[], after as ExperimentMetric[])
        )
        .with({ field: 'exposure_criteria' }, ({ before, after }) => {
            /**
             * exposure criteria is by default `{filter_test_accounts: true}`,
             * meaning that we use `feature_flag_called` as the event and
             * first seen as the varian handling.
             *
             * if the experiment has a `null` exposure criteria, a created action is logged.
             */
            const typedAfter = after as ExperimentExposureCriteria
            const typedBefore = before as ExperimentExposureCriteria

            const changes: (string | JSX.Element | null)[] = Object.keys(after || {}).map((key) =>
                match(key as keyof ExperimentExposureCriteria)
                    .with('filterTestAccounts', () => {
                        if (typedAfter?.filterTestAccounts === typedBefore?.filterTestAccounts) {
                            return null
                        }

                        return typedAfter?.filterTestAccounts
                            ? 'added the test account filter'
                            : 'removed the test account filter'
                    })
                    .with('multiple_variant_handling', () => {
                        if (typedAfter?.multiple_variant_handling === typedBefore?.multiple_variant_handling) {
                            return null
                        }

                        return typedAfter?.multiple_variant_handling === 'first_seen'
                            ? 'changed the variant handling to "first seen"'
                            : 'changed the variant handling to "exclude from analysis"'
                    })
                    .with('exposure_config', () => {
                        const afterConfig = typedAfter?.exposure_config
                        const beforeConfig = typedBefore?.exposure_config

                        if (equal(afterConfig, beforeConfig)) {
                            return null
                        }

                        if (afterConfig) {
                            const displayName = getExposureConfigDisplayName(afterConfig)
                            return (
                                <span>
                                    set the exposure configuration to <LemonTag color="purple">{displayName}</LemonTag>
                                </span>
                            )
                        }
                        return null
                    })
                    .exhaustive()
            )

            // Check if exposure_config was removed (returning to default)
            if (typedBefore?.exposure_config && !typedAfter?.exposure_config) {
                changes.push(
                    <span>
                        set the exposure configuration to the <LemonTag color="purple">$feature_flag_called</LemonTag>{' '}
                        default
                    </span>
                )
            }

            return changes.filter(Boolean) as (string | JSX.Element)[]
        })
        .otherwise(() => null)
}
