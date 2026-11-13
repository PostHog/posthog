import { useActions, useValues } from 'kea'

import { IconBook } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    IconStack,
    IconStackItem,
} from '@posthog/quill'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { urls } from 'scenes/urls'

import { QuillCopyAgentSetupPromptButton } from '../components/QuillCopyAgentSetupPromptButton'
import { QuillSetupWithPostHogAIButton } from '../components/QuillSetupWithPostHogAIButton'
import { metricsIntroLogic } from '../metricsIntroLogic'
import { MetricsHowItWorksDiagram } from './MetricsHowItWorksDiagram'

export function CatalogMetricsEmptyState(): JSX.Element {
    const { isMaxAvailable } = useValues(maxGlobalLogic)
    const { reportIntroShown } = useActions(metricsIntroLogic)

    // The diagram explains metrics in full, so the short intro does not show once metrics exist.
    useOnMountEffect(() => reportIntroShown('empty_state'))

    return (
        <Empty className="gap-6" data-attr="data-catalog-metrics-empty">
            <EmptyHeader>
                <IconStack>
                    <IconStackItem color="var(--color-product-data-catalog-light)">
                        <IconBook />
                    </IconStackItem>
                </IconStack>
                <EmptyTitle>No metrics yet</EmptyTitle>
                <EmptyDescription>
                    A metric is the one definition of a number your team agrees on, like revenue or active users.
                </EmptyDescription>
            </EmptyHeader>
            <MetricsHowItWorksDiagram />
            <EmptyContent className="flex-row flex-wrap justify-center">
                {isMaxAvailable && <QuillSetupWithPostHogAIButton source="empty_state" />}
                <Button
                    variant="outline"
                    render={<LinkPrimitive to={urls.dataCatalogNewMetric()} />}
                    // pinned: data-attr values feed autocapture dashboards, shared with the other new-metric entry points
                    data-attr="data-catalog-new-metric-button"
                >
                    Define your first metric
                </Button>
                <QuillCopyAgentSetupPromptButton source="empty_state" />
            </EmptyContent>
        </Empty>
    )
}
