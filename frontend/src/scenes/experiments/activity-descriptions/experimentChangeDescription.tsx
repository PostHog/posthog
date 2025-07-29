import clsx from 'clsx'
import { ActivityChange } from 'lib/components/ActivityLog/humanizeActivity'
import { dayjs } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'
import { CONCLUSION_DISPLAY_CONFIG } from 'scenes/experiments/constants'
import { urls } from 'scenes/urls'
import { match } from 'ts-pattern'
import { Experiment, ExperimentConclusion } from '~/types'

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
type AllowedExperimentFields = Pick<Experiment, 'conclusion' | 'start_date' | 'end_date' | 'metrics'> & {
    deleted: boolean
}

export const getExperimentChangeDescription = (experimentChange: ActivityChange): string | JSX.Element | null => {
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
        .otherwise(() => null)
}
