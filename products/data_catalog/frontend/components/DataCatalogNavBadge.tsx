import { useValues } from 'kea'

import { IconTableOfContents } from '@posthog/icons'

import { IconWithCount } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { catalogRestructureEnabled } from 'products/data_modeling/frontend/catalogRestructure'

import { dataCatalogAttentionLogic } from '../dataCatalogAttentionLogic'

export interface DataCatalogNavBadgeProps {
    className?: string
}

function AttentionIcon({ className }: DataCatalogNavBadgeProps): JSX.Element {
    const { totalCount, hasFailures } = useValues(dataCatalogAttentionLogic)

    return (
        <IconWithCount
            count={totalCount}
            showZero={false}
            status={hasFailures ? 'danger' : 'primary'}
            className={className}
        >
            <IconTableOfContents />
        </IconWithCount>
    )
}

export function DataCatalogNavBadge({ className }: DataCatalogNavBadgeProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!catalogRestructureEnabled(featureFlags)) {
        return <IconTableOfContents className={className} />
    }
    return <AttentionIcon className={className} />
}
