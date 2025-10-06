import { match } from 'ts-pattern'

import { ActivityChange } from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { SharedMetric } from '../SharedMetrics/sharedMetricLogic'

/**
 * id an id is provided, it returns a link to the shared metric. Otherwise, just the name.
 */
export const nameOrLinkToSharedMetric = (name: string | null, id?: string): JSX.Element | string => {
    if (id) {
        return <Link to={urls.experimentsSharedMetric(id)}>{name}</Link>
    }

    return name || '(unknown)'
}

/**
 * list of allowed fields for shared metric changes
 */
type AllowedSharedMetricFields = Pick<SharedMetric, 'query'>

export const getSharedMetricChangeDescription = (sharedMetricChange: ActivityChange): string | JSX.Element | null => {
    /**
     * a little type assertion to force field into the allowed shared metric fields
     */
    return match(sharedMetricChange as ActivityChange & { field: keyof AllowedSharedMetricFields })
        .with({ field: 'query' }, () => {
            return 'updated shared metric:'
        })
        .otherwise(() => null)
}
