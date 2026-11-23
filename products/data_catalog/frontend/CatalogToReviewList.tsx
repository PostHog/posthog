import { useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconChevronRight } from '@posthog/icons'
import { Button, Heading, Item, ItemActions, ItemContent, ItemGroup, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { PROPOSED_TABLES_FILTER, TABLES_FILTER_PARAM } from './catalogTableRows'
import { certificationsLogic } from './certificationsLogic'
import { metricsLogic } from './metricsLogic'
import { relationshipsLogic } from './relationshipsLogic'

const HEADING_ID = 'data-catalog-to-review-heading'

interface ReviewRowProps {
    label: string
    /** The number of items to review. Zero hides the row. */
    count: number
    /** The singular name of one item, for the text of the link. */
    noun: string
    href: string
    dataAttr: string
}

export interface CatalogToReviewListProps {
    suggestionsBanner?: JSX.Element
    /** Measures that the usage scan found with no metric. Zero hides the row. */
    suggestedMetricCount?: number
}

function proposedUrl(tab: 'tables' | 'relationships' | 'metrics'): string {
    return combineUrl(urls.dataCatalog(tab), { [TABLES_FILTER_PARAM]: PROPOSED_TABLES_FILTER }).url
}

function ReviewRow({ label, count, noun, href, dataAttr }: ReviewRowProps): JSX.Element | null {
    if (count === 0) {
        return null
    }
    return (
        <Item variant="outline" size="sm" className="flex-wrap">
            <ItemContent>
                <Text size="sm" className="text-secondary">
                    {label}
                </Text>
            </ItemContent>
            <ItemActions className="flex-wrap">
                <Button variant="outline" size="sm" render={<LinkPrimitive to={href} />} data-attr={dataAttr}>
                    {pluralize(count, noun)}
                    <IconChevronRight />
                </Button>
            </ItemActions>
        </Item>
    )
}

export function CatalogToReviewList({
    suggestionsBanner,
    suggestedMetricCount = 0,
}: CatalogToReviewListProps): JSX.Element | null {
    const { proposedCount: proposedMetrics } = useValues(metricsLogic)
    const { proposedCount: proposedCertifications } = useValues(certificationsLogic)
    const { pendingCount: proposedJoins } = useValues(relationshipsLogic)

    const reviewCount = proposedMetrics + suggestedMetricCount + proposedCertifications + proposedJoins
    if (!suggestionsBanner && reviewCount === 0) {
        return null
    }

    return (
        <section aria-labelledby={HEADING_ID} className="flex flex-col gap-2">
            <Heading size="base" render={<h3 id={HEADING_ID} className="m-0" />}>
                To review
            </Heading>
            {/* pinned: autocapture reads the data-attr values of the rows, so each one keeps its spelling */}
            <ItemGroup combined role={undefined}>
                {suggestionsBanner}
                <ReviewRow
                    label="Metrics to approve"
                    count={proposedMetrics}
                    noun="metric"
                    href={proposedUrl('metrics')}
                    dataAttr="data-catalog-review-metrics"
                />
                {/* The Metrics tab shows the suggestions first, so the link needs no filter. */}
                <ReviewRow
                    label="Suggested metrics (extracted by usage patterns)"
                    count={suggestedMetricCount}
                    noun="metric"
                    href={urls.dataCatalog('metrics')}
                    dataAttr="data-catalog-review-suggested-metrics"
                />
                <ReviewRow
                    label="Certifications waiting for approval"
                    count={proposedCertifications}
                    noun="certification"
                    href={proposedUrl('tables')}
                    dataAttr="data-catalog-review-certifications"
                />
                <ReviewRow
                    label="Relationships waiting for approval"
                    count={proposedJoins}
                    noun="join"
                    href={proposedUrl('relationships')}
                    dataAttr="data-catalog-review-relationships"
                />
            </ItemGroup>
        </section>
    )
}
