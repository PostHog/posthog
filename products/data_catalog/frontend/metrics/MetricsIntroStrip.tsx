import { useActions } from 'kea'

import { IconInfo, IconX } from '@posthog/icons'
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
        <Item variant="outline" size="xs" className="w-fit max-w-full flex-wrap" data-attr="data-catalog-metrics-intro">
            <ItemMedia variant="icon">
                <IconInfo />
            </ItemMedia>
            <ItemContent className="min-w-0">
                {/* One flowing paragraph, so it wraps like a sentence in a narrow scene instead of stacking. */}
                <p className="m-0 text-xs">
                    <span className="font-medium">How metrics work:</span> when a teammate asks an agent a question, the
                    agent finds the matching metric here and computes it from its definition.{' '}
                    <Badge variant="warning" className="align-middle">
                        Proposed
                    </Badge>{' '}
                    ones carry a warning until approved.
                </p>
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
