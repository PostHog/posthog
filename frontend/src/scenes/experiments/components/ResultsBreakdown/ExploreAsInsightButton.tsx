import { IconAreaChart } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import type { InsightVizNode } from '~/queries/schema/schema-general'

export function ExploreAsInsightButton({ query }: { query: InsightVizNode }): JSX.Element | null {
    if (!query) {
        return null
    }

    return (
        <LemonButton
            className="ml-auto -translate-y-2"
            size="xsmall"
            type="primary"
            icon={<IconAreaChart />}
            to={urls.insightNew({ query })}
            targetBlank
        >
            Explore as Insight
        </LemonButton>
    )
}
