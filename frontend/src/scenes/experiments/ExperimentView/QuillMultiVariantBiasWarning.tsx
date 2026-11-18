import { IconWarning } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { MULTIPLE_EXPOSURES_DOCS_URL } from 'products/experiments/frontend/constants'

export function QuillMultiVariantBiasWarning({
    multipleVariantPercentage,
    onOpenDocs,
    onAdjustDistribution,
    onUseFirstSeen,
}: {
    multipleVariantPercentage: number
    onOpenDocs: () => void
    onAdjustDistribution: () => void
    onUseFirstSeen: () => void
}): JSX.Element {
    return (
        <Item variant="outline" size="sm" tone="warning" className="mt-4" data-attr="experiment-bias-warning">
            <ItemMedia variant="icon" aria-hidden>
                <IconWarning />
            </ItemMedia>
            <ItemContent className="min-w-0">
                <ItemTitle>The uneven split may bias the results</ItemTitle>
                <ItemDescription className="flex flex-col gap-1">
                    <span>
                        <strong>{multipleVariantPercentage.toFixed(1)}%</strong> of users were exposed to multiple
                        variants. With your uneven variant split and the current <strong>Exclude</strong> handling,
                        users were disproportionately dropped from the smaller variant. If their behavior differs from
                        other users, the smaller variant's metrics will be biased.
                    </span>
                    <span>
                        We recommend using an <strong>even split</strong> and controlling exposure with the overall
                        rollout (uneven splits have further disadvantages). Alternatively use{' '}
                        <Button
                            variant="link"
                            size="inline"
                            nativeButton={false}
                            render={
                                <LinkPrimitive to={MULTIPLE_EXPOSURES_DOCS_URL} target="_blank" onClick={onOpenDocs} />
                            }
                        >
                            First seen
                        </Button>{' '}
                        handling.
                    </span>
                </ItemDescription>
            </ItemContent>
            <ItemActions>
                <Button variant="outline" onClick={onAdjustDistribution}>
                    Adjust distribution
                </Button>
                <Button variant="outline" onClick={onUseFirstSeen}>
                    Use first seen variant
                </Button>
            </ItemActions>
        </Item>
    )
}
