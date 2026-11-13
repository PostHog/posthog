import { useActions } from 'kea'

import { IconArrowRight, IconInfo, IconX } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemMedia } from '@posthog/quill'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { DATA_CATALOG_DOCS_URL } from '../common'
import { metricsIntroLogic } from '../metricsIntroLogic'

const INTRO_STEPS = [
    'A teammate asks an agent',
    'The agent looks up the metric here',
    'It computes the number from the approved definition',
]

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
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                    <span className="font-medium">How metrics work:</span>
                    <ol aria-label="How metrics work" className="m-0 contents list-none p-0">
                        {INTRO_STEPS.map((step, index) => (
                            <li key={step} className="flex items-center gap-2">
                                {index > 0 && (
                                    <IconArrowRight aria-hidden className="size-3 shrink-0 text-muted-foreground" />
                                )}
                                <span>{step}</span>
                            </li>
                        ))}
                    </ol>
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
