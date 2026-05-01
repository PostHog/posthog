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

export const getSharedMetricChangeDescription = (sharedMetricChange: ActivityChange): string | JSX.Element => {
    /**
     * a little type assertion to force field into the allowed shared metric fields
     */
    return match(sharedMetricChange as ActivityChange & { field: keyof AllowedSharedMetricFields })
        .with({ field: 'query' }, () => {
            return 'updated shared metric:'
        })
        .otherwise(() => {
            if (!sharedMetricChange.field) {
                return 'updated shared metric'
            }
            // Fallback for unhandled fields - ensures all activity is visible
            const fieldName = sharedMetricChange.field.replace(/_/g, ' ')
            return match(sharedMetricChange.action)
                .with('created', () => `added ${fieldName} to`)
                .with('deleted', () => `removed ${fieldName} from`)
                .with('changed', () => `updated ${fieldName} for`)
                .otherwise(() => `modified ${fieldName} for`)
        })
}
