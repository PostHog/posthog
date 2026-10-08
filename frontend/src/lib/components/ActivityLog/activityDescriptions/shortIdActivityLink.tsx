import { Link } from 'lib/lemon-ui/Link'

import { InsightShortId } from '~/types'

import { ActivityLogItem } from '../humanizeActivity'

export function shortIdActivityLink(
    logItem: ActivityLogItem | undefined,
    urlForId: (id: InsightShortId) => string
): JSX.Element {
    const name = logItem?.detail.name
    const shortId = logItem?.detail.short_id
    return shortId ? <Link to={urlForId(shortId)}>{name || 'unknown'}</Link> : name ? <>{name}</> : <i>Untitled</i>
}
