import { useActions } from 'kea'

import { IconArrowRight, IconInfo, IconX } from '@posthog/icons'
import { Badge, Button, Item, ItemActions, ItemContent, ItemMedia } from '@posthog/quill'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { DATA_CATALOG_DOCS_URL } from '../common'
import { metricsIntroLogic } from '../metricsIntroLogic'

/** A one-line version of the empty-state diagram, for a person's first visit to a catalog that has metrics. */
export function MetricsIntroStrip(): JSX.Element {
    const { reportIntroShown, dismissIntro } = useActions(metricsIntroLogic)

    useOnMountEffect(() => reportIntroShown('strip'))

    return (
        <Item variant="muted" size="xs" className="flex-wrap" data-attr="data-catalog-metrics-intro">
            <ItemMedia variant="icon">
                <IconInfo />
            </ItemMedia>
            <ItemContent className="min-w-0">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                    <span className="font-medium">How metrics work:</span>
                    <span className="inline-flex items-center gap-1.5">
                        <Badge variant="warning">Proposed</Badge>
                        <span>a teammate reviews it</span>
                    </span>
                    <IconArrowRight aria-hidden className="size-3 shrink-0 text-muted-foreground" />
                    <span className="inline-flex items-center gap-1.5">
                        <Badge variant="success">Approved</Badge>
                        <span>PostHog AI and agents compute the number from it</span>
                    </span>
                </div>
            </ItemContent>
            <ItemActions>
                <Button
                    variant="link"
                    size="sm"
                    render={<LinkPrimitive to={DATA_CATALOG_DOCS_URL} target="_blank" />}
                    data-attr="data-catalog-metrics-intro-docs"
                >
                    Learn more
                </Button>
                <Button
                    size="icon-sm"
                    aria-label="Dismiss"
                    tooltip="Dismiss"
                    onClick={dismissIntro}
                    data-attr="data-catalog-metrics-intro-dismiss"
                >
                    <IconX />
                </Button>
            </ItemActions>
        </Item>
    )
}
