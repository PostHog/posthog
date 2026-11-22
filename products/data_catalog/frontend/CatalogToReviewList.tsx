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

interface ReviewLink {
    key: string
    title: string
    href: string
}

export interface CatalogToReviewListProps {
    suggestionsBanner?: JSX.Element
    /** Measures that the usage scan found with no metric. Zero hides the row. */
    suggestedMetricCount?: number
}

function proposedUrl(tab: 'tables' | 'relationships' | 'metrics'): string {
    return combineUrl(urls.dataCatalog(tab), { [TABLES_FILTER_PARAM]: PROPOSED_TABLES_FILTER }).url
}

/** No link when there is nothing to review, so a row with no link does not show. */
function reviewLinks(key: string, count: number, noun: string, href: string): ReviewLink[] {
    return count > 0 ? [{ key, title: pluralize(count, noun), href }] : []
}

function ReviewRow({ label, links }: { label: string; links: ReviewLink[] }): JSX.Element | null {
    if (links.length === 0) {
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
                {links.map(({ key, title, href }) => (
                    <Button
                        key={key}
                        variant="outline"
                        size="sm"
                        render={<LinkPrimitive to={href} />}
                        // pinned: autocapture reads the data-attr values, so each key keeps its spelling
                        data-attr={`data-catalog-review-${key}`}
                    >
                        {title}
                        <IconChevronRight />
                    </Button>
                ))}
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

    const tableLinks = [
        ...reviewLinks('certifications', proposedCertifications, 'certification', proposedUrl('tables')),
        ...reviewLinks('relationships', proposedJoins, 'join', proposedUrl('relationships')),
    ]
    const metricLinks = reviewLinks('metrics', proposedMetrics, 'metric', proposedUrl('metrics'))
    // The Metrics tab shows the suggestions first, so the link needs no filter.
    const suggestedLinks = reviewLinks('suggested-metrics', suggestedMetricCount, 'metric', urls.dataCatalog('metrics'))

    if (!suggestionsBanner && tableLinks.length + metricLinks.length + suggestedLinks.length === 0) {
        return null
    }

    return (
        <section aria-labelledby={HEADING_ID} className="flex flex-col gap-2">
            <Heading size="base" render={<h3 id={HEADING_ID} className="m-0" />}>
                To review
            </Heading>
            <ItemGroup combined role={undefined}>
                {suggestionsBanner}
                <ReviewRow label="Waiting for approval" links={tableLinks} />
                <ReviewRow label="Metrics to approve" links={metricLinks} />
                <ReviewRow label="Suggested metrics (extracted by usage patterns)" links={suggestedLinks} />
            </ItemGroup>
        </section>
    )
}
