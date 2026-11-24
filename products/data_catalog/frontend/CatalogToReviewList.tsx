import { useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconChevronRight } from '@posthog/icons'
import { Button, Heading, Item, ItemActions, ItemContent, ItemGroup, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { PROPOSED_TABLES_FILTER, SUGGESTED_METRICS_FILTER, TABLES_FILTER_PARAM } from './catalogTableRows'
import { certificationsLogic } from './certificationsLogic'
import { metricsLogic } from './metricsLogic'
import { relationshipsLogic } from './relationshipsLogic'

const HEADING_ID = 'data-catalog-to-review-heading'

interface ReviewLink {
    count: number
    noun: string
    href: string
    dataAttr: string
}

export interface CatalogToReviewListProps {
    suggestionsBanner?: JSX.Element
    suggestedMetricCount?: number
}

function reviewUrl(tab: 'tables' | 'relationships' | 'metrics', filter: string = PROPOSED_TABLES_FILTER): string {
    return combineUrl(urls.dataCatalog(tab), { [TABLES_FILTER_PARAM]: filter }).url
}

function ReviewRow({ label, links }: { label: string; links: ReviewLink[] }): JSX.Element | null {
    const linksToShow = links.filter(({ count }) => count > 0)
    if (linksToShow.length === 0) {
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
                {linksToShow.map(({ count, noun, href, dataAttr }) => (
                    <Button
                        key={dataAttr}
                        variant="outline"
                        size="sm"
                        render={<LinkPrimitive to={href} />}
                        data-attr={dataAttr}
                    >
                        {pluralize(count, noun)}
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
                    links={[
                        {
                            count: proposedMetrics,
                            noun: 'metric',
                            href: reviewUrl('metrics'),
                            dataAttr: 'data-catalog-review-metrics',
                        },
                    ]}
                />
                <ReviewRow
                    label="Suggested metrics (extracted by usage patterns)"
                    links={[
                        {
                            count: suggestedMetricCount,
                            noun: 'metric',
                            href: reviewUrl('metrics', SUGGESTED_METRICS_FILTER),
                            dataAttr: 'data-catalog-review-suggested-metrics',
                        },
                    ]}
                />
                <ReviewRow
                    label="Relationships waiting for approval"
                    links={[
                        {
                            count: proposedCertifications,
                            noun: 'certification',
                            href: reviewUrl('tables'),
                            dataAttr: 'data-catalog-review-certifications',
                        },
                        {
                            count: proposedJoins,
                            noun: 'join',
                            href: reviewUrl('relationships'),
                            dataAttr: 'data-catalog-review-relationships',
                        },
                    ]}
                />
            </ItemGroup>
        </section>
    )
}
