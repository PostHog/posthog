import { useActions, useValues } from 'kea'
import React from 'react'

import { IconChevronDown, IconCode, IconFlask, IconSparkles, IconWrench } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { maxLogic } from 'scenes/max/maxLogic'
import { createSuggestionGroup } from 'scenes/max/utils'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_PANEL_ID } from '~/layout/ai/aiPanelIds'
import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { SidePanelTab } from '~/types'

import { INTENT_KEYS, INTENT_METADATA } from 'products/feature_flags/frontend/featureFlagTemplateConstants'

import { AI_SUGGESTIONS, AI_TOOL_DEFINITION, TEMPLATES, TEMPLATE_METADATA } from './NewFeatureFlagMenu'

export function QuillNewFeatureFlagMenu({ disabledReason }: { disabledReason?: string | null }): JSX.Element {
    const { featureFlags } = useValues(enabledFeaturesLogic)
    const { setActiveGroup } = useActions(maxLogic({ panelId: SIDE_PANEL_PANEL_ID }))
    const { openSidePanel } = useActions(sidePanelLogic)

    const intentsEnabled = !!featureFlags[FEATURE_FLAGS.FEATURE_FLAG_CREATION_INTENTS]

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="primary"
                        size="icon"
                        aria-label="New feature flag options"
                        tooltip="New feature flag options"
                        disabledReason={disabledReason}
                        data-attr="new-feature-flag-dropdown"
                    />
                }
            >
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-64">
                {TEMPLATES.map((template) => {
                    const metadata = TEMPLATE_METADATA[template]
                    if (intentsEnabled) {
                        return (
                            <DropdownMenuSub key={template}>
                                <DropdownMenuSubTrigger
                                    data-attr="new-feature-flag-menu-item"
                                    data-attr-template={template}
                                    description={metadata.description}
                                >
                                    <metadata.icon />
                                    {metadata.name}
                                </DropdownMenuSubTrigger>
                                <DropdownMenuSubContent className="min-w-64">
                                    {INTENT_KEYS.map((intentKey) => {
                                        const intentMeta = INTENT_METADATA[intentKey]
                                        return (
                                            <DropdownMenuItem
                                                key={intentKey}
                                                render={
                                                    <Button
                                                        size="row"
                                                        left
                                                        render={
                                                            <LinkPrimitive
                                                                to={urls.featureFlagNew({
                                                                    template,
                                                                    intent: intentKey,
                                                                })}
                                                            />
                                                        }
                                                    />
                                                }
                                                data-attr="new-feature-flag-menu-intent"
                                                data-attr-intent={intentKey}
                                                description={intentMeta.description}
                                            >
                                                <intentMeta.icon />
                                                {intentMeta.name}
                                            </DropdownMenuItem>
                                        )
                                    })}
                                    <DropdownMenuSeparator />
                                    <DropdownMenuItem
                                        render={
                                            <Button
                                                size="row"
                                                left
                                                render={<LinkPrimitive to={urls.featureFlagNew({ template })} />}
                                            />
                                        }
                                        data-attr="new-feature-flag-menu-skip-intent"
                                    >
                                        <span className="text-xs text-secondary">Skip — no evaluation warnings</span>
                                    </DropdownMenuItem>
                                </DropdownMenuSubContent>
                            </DropdownMenuSub>
                        )
                    }
                    return (
                        <DropdownMenuItem
                            key={template}
                            render={
                                <Button
                                    size="row"
                                    left
                                    render={<LinkPrimitive to={urls.featureFlagNew({ template })} />}
                                />
                            }
                            data-attr="new-feature-flag-menu-item"
                            data-attr-template={template}
                            description={metadata.description}
                        >
                            <metadata.icon />
                            {metadata.name}
                        </DropdownMenuItem>
                    )
                })}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                    render={
                        <Button
                            size="row"
                            left
                            render={<LinkPrimitive to={urls.featureFlagNew({ type: 'remote_config' })} />}
                        />
                    }
                    data-attr="new-feature-flag-menu-item"
                    data-attr-template="remote_config"
                    description="Deliver configuration values to your app"
                >
                    <IconCode />
                    Remote config
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                    data-attr="new-experiment-menu-item"
                    data-attr-flag-type="experiment"
                    description="Run A/B tests with statistical analysis"
                    render={<Button size="row" left render={<LinkPrimitive to={urls.experiment('new')} />} />}
                    onClick={() => {
                        void addProductIntentForCrossSell({
                            from: ProductKey.FEATURE_FLAGS,
                            to: ProductKey.EXPERIMENTS,
                            intent_context: ProductIntentContext.EXPERIMENT_CREATED,
                        })
                    }}
                >
                    <IconFlask />
                    Experiment
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                    data-attr="new-feature-flag-ai-menu-item"
                    data-attr-flag-type="ai"
                    description="Not sure? Ask AI to do it for you"
                    onClick={() => {
                        setActiveGroup(
                            createSuggestionGroup(
                                AI_TOOL_DEFINITION.name,
                                React.createElement(IconWrench),
                                AI_SUGGESTIONS
                            )
                        )
                        openSidePanel(SidePanelTab.Max, 'Create a feature flag for ')
                    }}
                >
                    <IconSparkles />
                    Ask AI
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
