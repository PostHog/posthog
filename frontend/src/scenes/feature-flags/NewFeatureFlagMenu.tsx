import { useActions } from 'kea'
import React from 'react'

import { IconCode, IconFlask, IconPeople, IconSparkles, IconTestTube, IconToggle, IconWrench } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { getToolDefinition } from 'scenes/max/max-constants'
import { maxLogic } from 'scenes/max/maxLogic'
import { createSuggestionGroup } from 'scenes/max/utils'
import { urls } from 'scenes/urls'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { SidePanelTab } from '~/types'

type FeatureFlagTemplate = 'simple' | 'targeted' | 'multivariate' | 'targeted-multivariate'

interface TemplateMetadata {
    name: string
    description: string
    icon: React.ComponentType
    url: string
}

const TEMPLATE_METADATA: Record<FeatureFlagTemplate, TemplateMetadata> = {
    simple: {
        name: 'Simple flag',
        description: 'On/off for all users',
        icon: IconToggle,
        url: urls.featureFlagNew({ template: 'simple' }),
    },
    targeted: {
        name: 'Targeted release',
        description: 'Release to specific users',
        icon: IconPeople,
        url: urls.featureFlagNew({ template: 'targeted' }),
    },
    multivariate: {
        name: 'Multivariate',
        description: 'Multiple variants',
        icon: IconTestTube,
        url: urls.featureFlagNew({ template: 'multivariate' }),
    },
    'targeted-multivariate': {
        name: 'Targeted multivariate',
        description: 'Variants for specific users',
        icon: IconFlask,
        url: urls.featureFlagNew({ template: 'targeted-multivariate' }),
    },
}

const TEMPLATES: FeatureFlagTemplate[] = ['simple', 'targeted', 'multivariate', 'targeted-multivariate']

const AI_TOOL_DEFINITION = getToolDefinition('create_feature_flag')!
const AI_SUGGESTIONS = [
    'Create a flag to gradually roll out…',
    'Create a flag that starts at 10% rollout for…',
    'Create a multivariate flag for…',
    'Create a beta testing flag for…',
]

export function OverlayForNewFeatureFlagMenu(): JSX.Element {
    const { setActiveGroup } = useActions(maxLogic({ tabId: 'sidepanel' }))
    const { openSidePanel } = useActions(sidePanelLogic)

    return (
        <>
            {TEMPLATES.map((template) => {
                const metadata = TEMPLATE_METADATA[template]
                return (
                    <LemonButton
                        key={template}
                        icon={<metadata.icon />}
                        to={metadata.url}
                        data-attr="new-feature-flag-menu-item"
                        data-attr-template={template}
                        fullWidth
                    >
                        <div className="flex flex-col text-sm py-1">
                            <strong>{metadata.name}</strong>
                            <span className="text-xs font-sans font-normal">{metadata.description}</span>
                        </div>
                    </LemonButton>
                )
            })}
            <LemonDivider className="my-1" />
            <LemonButton
                icon={<IconCode />}
                to={urls.featureFlagNew({ type: 'remote_config' })}
                data-attr="new-feature-flag-menu-item"
                data-attr-template="remote_config"
                fullWidth
            >
                <div className="flex flex-col text-sm py-1">
                    <strong>Remote config</strong>
                    <span className="text-xs font-sans font-normal">Deliver configuration values to your app</span>
                </div>
            </LemonButton>
            <LemonDivider className="my-1" />
            <LemonButton
                icon={<IconFlask />}
                to={urls.experiment('new')}
                data-attr="new-experiment-menu-item"
                data-attr-flag-type="experiment"
                onClick={() => {
                    void addProductIntentForCrossSell({
                        from: ProductKey.FEATURE_FLAGS,
                        to: ProductKey.EXPERIMENTS,
                        intent_context: ProductIntentContext.EXPERIMENT_CREATED,
                    })
                }}
                fullWidth
            >
                <div className="flex flex-col text-sm py-1">
                    <strong>Experiment</strong>
                    <span className="text-xs font-sans font-normal">Run A/B tests with statistical analysis</span>
                </div>
            </LemonButton>
            <LemonDivider />
            <LemonButton
                icon={<IconSparkles />}
                data-attr="new-feature-flag-ai-menu-item"
                data-attr-flag-type="ai"
                onClick={() => {
                    // Show the suggestions from the feature flag tool
                    setActiveGroup(
                        createSuggestionGroup(AI_TOOL_DEFINITION.name, React.createElement(IconWrench), AI_SUGGESTIONS)
                    )
                    openSidePanel(SidePanelTab.Max, 'Create a feature flag for ')
                }}
                fullWidth
            >
                <div className="flex flex-col text-sm py-1">
                    <strong>Ask AI</strong>
                    <span className="text-xs font-sans font-normal">Not sure? Ask AI to do it for you</span>
                </div>
            </LemonButton>
        </>
    )
}
