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

interface ProposalLink {
    key: string
    count: number
    title: string
    href: string
}

export interface CatalogToReviewListProps {
    suggestionsBanner?: JSX.Element
}

function proposedUrl(tab: 'tables' | 'relationships' | 'metrics'): string {
    return combineUrl(urls.dataCatalog(tab), { [TABLES_FILTER_PARAM]: PROPOSED_TABLES_FILTER }).url
}

export function CatalogToReviewList({ suggestionsBanner }: CatalogToReviewListProps): JSX.Element | null {
    const { proposedCount: proposedMetrics } = useValues(metricsLogic)
    const { proposedCount: proposedCertifications } = useValues(certificationsLogic)
    const { pendingCount: proposedJoins } = useValues(relationshipsLogic)

    const proposals: ProposalLink[] = [
        {
            key: 'certifications',
            count: proposedCertifications,
            title: pluralize(proposedCertifications, 'certification'),
            href: proposedUrl('tables'),
        },
        {
            key: 'relationships',
            count: proposedJoins,
            title: pluralize(proposedJoins, 'join'),
            href: proposedUrl('relationships'),
        },
        {
            key: 'metrics',
            count: proposedMetrics,
            title: pluralize(proposedMetrics, 'metric'),
            href: proposedUrl('metrics'),
        },
    ].filter(({ count }) => count > 0)

    if (!suggestionsBanner && proposals.length === 0) {
        return null
    }

    return (
        <section aria-labelledby={HEADING_ID} className="flex flex-col gap-2">
            <Heading size="base" render={<h3 id={HEADING_ID} className="m-0" />}>
                To review
            </Heading>
            <ItemGroup combined role={undefined}>
                {suggestionsBanner}
                {proposals.length > 0 && (
                    <Item variant="outline" size="sm" className="flex-wrap">
                        <ItemContent>
                            <Text size="sm" className="text-secondary">
                                Waiting for approval
                            </Text>
                        </ItemContent>
                        <ItemActions className="flex-wrap">
                            {proposals.map(({ key, title, href }) => (
                                <Button
                                    key={key}
                                    variant="outline"
                                    size="sm"
                                    render={<LinkPrimitive to={href} />}
                                    data-attr={`data-catalog-review-${key}`}
                                >
                                    {title}
                                    <IconChevronRight />
                                </Button>
                            ))}
                        </ItemActions>
                    </Item>
                )}
            </ItemGroup>
        </section>
    )
}
