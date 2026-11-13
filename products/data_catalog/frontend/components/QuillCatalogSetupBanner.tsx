import { useActions, useValues } from 'kea'

import { IconSparkles, IconX } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from '@posthog/quill'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import { catalogSetupLogic } from '../catalogSetupLogic'
import { QuillCopyAgentSetupPromptButton } from './QuillCopyAgentSetupPromptButton'
import { QuillSetupWithPostHogAIButton } from './QuillSetupWithPostHogAIButton'

export function QuillCatalogSetupBanner(): JSX.Element | null {
    const { showSetupBanner } = useValues(catalogSetupLogic)

    if (!showSetupBanner) {
        return null
    }
    return <VisibleQuillCatalogSetupBanner />
}

/** Split out so the impression event fires once, when the banner first shows, not on every render. */
function VisibleQuillCatalogSetupBanner(): JSX.Element {
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
                    {isMaxAvailable ? 'Let PostHog AI draft your catalog' : 'Let your agent draft your catalog'}
                </ItemTitle>
                <ItemDescription>
                    It looks at the insights and dashboards your team uses most and proposes metrics for you to review.
                    Nothing is approved until you approve it.
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
