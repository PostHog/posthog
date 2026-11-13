import { useActions, useValues } from 'kea'

import { IconSparkles, IconX } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from '@posthog/quill'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import { catalogSetupLogic } from '../catalogSetupLogic'
import { QuillCopyAgentSetupPromptButton } from './QuillCopyAgentSetupPromptButton'
import { QuillSetupWithPostHogAIButton } from './QuillSetupWithPostHogAIButton'

/** The metrics section mounts it only when it is the notice to show, so the impression event fires once per showing. */
export function QuillCatalogSetupBanner(): JSX.Element {
    const { isMaxAvailable } = useValues(maxGlobalLogic)
    const { dismissSetupBanner, reportSetupBannerShown } = useActions(catalogSetupLogic)

    useOnMountEffect(reportSetupBannerShown)

    return (
        <Item variant="outline" size="sm" tone="info" className="flex-wrap" data-attr="data-catalog-setup-banner">
            <ItemMedia variant="icon">
                <IconSparkles />
            </ItemMedia>
            <ItemContent className="min-w-60">
                <ItemTitle>
                    {isMaxAvailable ? 'Let PostHog AI draft your catalog' : 'Draft your catalog with an AI agent'}
                </ItemTitle>
                <ItemDescription>
                    It proposes metrics from the insights and dashboards your team uses most. Agents can use a proposed
                    metric, with a warning, until someone on your team approves it.
                </ItemDescription>
            </ItemContent>
            <ItemActions className="flex-wrap">
                {isMaxAvailable && <QuillSetupWithPostHogAIButton source="banner" size="sm" />}
                <QuillCopyAgentSetupPromptButton source="banner" size="sm" />
                <Button
                    size="icon-sm"
                    aria-label="Dismiss"
                    tooltip="Dismiss"
                    onClick={dismissSetupBanner}
                    data-attr="data-catalog-setup-banner-dismiss"
                >
                    <IconX />
                </Button>
            </ItemActions>
        </Item>
    )
}
