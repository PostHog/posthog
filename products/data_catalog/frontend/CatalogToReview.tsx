import { useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconLightBulb } from '@posthog/icons'
import {
    Button,
    Heading,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemTitle,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { PROPOSED_TABLES_FILTER, TABLES_FILTER_PARAM } from './catalogTableRows'
import { certificationsLogic } from './certificationsLogic'
import { metricsLogic } from './metricsLogic'
import { relationshipsLogic } from './relationshipsLogic'

const HEADING_ID = 'data-catalog-to-review-heading'

interface ReviewItem {
    key: string
    count: number
    title: string
    description: string
    href: string
}

export function CatalogToReview(): JSX.Element | null {
    const { proposedCount: proposedMetrics } = useValues(metricsLogic)
    const { proposedCount: proposedCertifications } = useValues(certificationsLogic)
    const { pendingCount: proposedJoins } = useValues(relationshipsLogic)

    const items: ReviewItem[] = [
        {
            key: 'certifications',
            count: proposedCertifications,
            title: pluralize(proposedCertifications, 'proposed certification'),
            description: 'Tables and views waiting for someone to mark them as trusted.',
            href: combineUrl(urls.dataCatalog('tables'), { [TABLES_FILTER_PARAM]: PROPOSED_TABLES_FILTER }).url,
        },
        {
            key: 'relationships',
            count: proposedJoins,
            title: pluralize(proposedJoins, 'proposed join'),
            description: 'Joins between tables waiting for someone to accept or reject them.',
            href: combineUrl(urls.dataCatalog('relationships'), { [TABLES_FILTER_PARAM]: PROPOSED_TABLES_FILTER }).url,
        },
        {
            key: 'metrics',
            count: proposedMetrics,
            title: pluralize(proposedMetrics, 'proposed metric'),
            description: 'Metric definitions waiting for approval.',
            href: combineUrl(urls.dataCatalog('metrics'), { [TABLES_FILTER_PARAM]: PROPOSED_TABLES_FILTER }).url,
        },
    ].filter(({ count }) => count > 0)

    if (items.length === 0) {
        return null
    }

    return (
        <section aria-labelledby={HEADING_ID} className="flex flex-col gap-2">
            <Heading size="base" render={<h3 id={HEADING_ID} className="m-0" />}>
                To review
            </Heading>
            <ItemGroup className="grid gap-2 @min-[48rem]/main-content:grid-cols-3">
                {items.map(({ key, title, description, href }) => (
                    <Item key={key} variant="outline" size="sm" render={<div role="listitem" />}>
                        <ItemMedia variant="icon">
                            <IconLightBulb />
                        </ItemMedia>
                        <ItemContent>
                            <ItemTitle>{title}</ItemTitle>
                            <ItemDescription>{description}</ItemDescription>
                        </ItemContent>
                        <ItemActions>
                            <Button
                                variant="outline"
                                size="sm"
                                render={<LinkPrimitive to={href} />}
                                data-attr={`data-catalog-review-${key}`}
                            >
                                Review
                            </Button>
                        </ItemActions>
                    </Item>
                ))}
            </ItemGroup>
        </section>
    )
}
