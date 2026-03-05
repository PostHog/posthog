import { useActions, useValues } from 'kea'
import React, { useState } from 'react'

import {
    IconArrowLeft,
    IconCode,
    IconFlask,
    IconPeople,
    IconSparkles,
    IconTestTube,
    IconToggle,
    IconWrench,
} from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { getToolDefinition } from 'scenes/max/max-constants'
import { maxLogic } from 'scenes/max/maxLogic'
import { createSuggestionGroup } from 'scenes/max/utils'
import { urls } from 'scenes/urls'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { SidePanelTab } from '~/types'

import { INTENT_KEYS, INTENT_METADATA, TemplateKey } from 'products/feature_flags/frontend/featureFlagTemplateConstants'

interface DropdownTemplateMetadata {
    name: string
    description: string
    icon: React.ComponentType
}

const TEMPLATE_METADATA: Record<TemplateKey, DropdownTemplateMetadata> = {
    simple: {
        name: 'Simple flag',
        description: 'On/off for all users',
        icon: IconToggle,
    },
    targeted: {
        name: 'Targeted release',
        description: 'Release to specific users',
        icon: IconPeople,
    },
    multivariate: {
        name: 'Multivariate',
        description: 'Multiple variants',
        icon: IconTestTube,
    },
    'targeted-multivariate': {
        name: 'Targeted multivariate',
        description: 'Variants for specific users',
        icon: IconFlask,
    },
}

const TEMPLATES: TemplateKey[] = ['simple', 'targeted', 'multivariate', 'targeted-multivariate']

const AI_TOOL_DEFINITION = getToolDefinition('create_feature_flag')!
const AI_SUGGESTIONS = [
    'Create a flag to gradually roll out…',
    'Create a flag that starts at 10% rollout for…',
    'Create a multivariate flag for…',
    'Create a beta testing flag for…',
]

function IntentSubmenu({ template, onBack }: { template: TemplateKey; onBack: () => void }): JSX.Element {
    const metadata = TEMPLATE_METADATA[template]

    return (
        <>
            <LemonButton icon={<IconArrowLeft />} onClick={onBack} fullWidth size="small">
                <span className="text-xs text-secondary">{metadata.name}</span>
            </LemonButton>
            <LemonDivider className="my-1" />
            {INTENT_KEYS.map((intentKey) => {
                const intentMeta = INTENT_METADATA[intentKey]
                return (
                    <LemonButton
                        key={intentKey}
                        icon={<intentMeta.icon />}
                        to={urls.featureFlagNew({ template, intent: intentKey })}
                        data-attr="new-feature-flag-menu-intent"
                        data-attr-intent={intentKey}
                        fullWidth
                    >
                        <div className="flex flex-col text-sm py-1">
                            <strong>{intentMeta.name}</strong>
                            <span className="text-xs font-sans font-normal">{intentMeta.description}</span>
                        </div>
                    </LemonButton>
                )
            })}
            <LemonDivider className="my-1" />
            <LemonButton
                to={urls.featureFlagNew({ template })}
                data-attr="new-feature-flag-menu-skip-intent"
                fullWidth
                size="small"
            >
                <span className="text-xs text-secondary">Skip — no evaluation warnings</span>
            </LemonButton>
        </>
    )
}

export function OverlayForNewFeatureFlagMenu(): JSX.Element {
    const { featureFlags } = useValues(enabledFeaturesLogic)
    const { setActiveGroup } = useActions(maxLogic({ tabId: 'sidepanel' }))
    const { openSidePanel } = useActions(sidePanelLogic)

    const intentsEnabled = !!featureFlags[FEATURE_FLAGS.FEATURE_FLAG_CREATION_INTENTS]
    // useState is intentional — this is an ephemeral popover overlay that unmounts on close
    const [selectedTemplate, setSelectedTemplate] = useState<TemplateKey | null>(null)

    if (intentsEnabled && selectedTemplate) {
        return <IntentSubmenu template={selectedTemplate} onBack={() => setSelectedTemplate(null)} />
    }

    return (
        <>
            {TEMPLATES.map((template) => {
                const metadata = TEMPLATE_METADATA[template]
                return (
                    <LemonButton
                        key={template}
                        icon={<metadata.icon />}
                        {...(intentsEnabled
                            ? { onClick: () => setSelectedTemplate(template) }
                            : { to: urls.featureFlagNew({ template }) })}
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
