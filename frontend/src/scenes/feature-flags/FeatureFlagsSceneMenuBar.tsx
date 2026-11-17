import { useActions } from 'kea'
import { router } from 'kea-router'
import posthog, { DisplaySurveyType } from 'posthog-js'
import React from 'react'

import {
    IconCode,
    IconFlag,
    IconFlask,
    IconMessage,
    IconPlus,
    IconPlusSmall,
    IconSparkles,
    IconWrench,
} from '@posthog/icons'
import { Button, ButtonGroup } from '@posthog/quill'

import { FeedbackSurveyButton } from 'lib/components/FeedbackSurveyButton/FeedbackSurveyButton'
import { RenderKeybind } from 'lib/components/Shortcuts/RenderKeybind'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { maxLogic } from 'scenes/max/maxLogic'
import { createSuggestionGroup } from 'scenes/max/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_PANEL_ID } from '~/layout/ai/aiPanelIds'
import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, SidePanelTab } from '~/types'

import { AI_SUGGESTIONS, AI_TOOL_DEFINITION, TEMPLATES, TEMPLATE_METADATA } from './NewFeatureFlagMenu'
import { QuillNewFeatureFlagMenu } from './QuillNewFeatureFlagMenu'

const RESOURCE_TYPE = 'feature_flags'

interface FeatureFlagsSceneMenuBarProps {
    feedbackSurveyId: string
    showRulesV2Editor: boolean
    rulesV2DisabledReason: string | null | undefined
    newFeatureFlagUrl: string
}

export function FeatureFlagsSceneMenuBar(props: FeatureFlagsSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <FeatureFlagsSceneMenuBarInner {...props} /> : null
}

function FeatureFlagsSceneMenuBarInner({
    feedbackSurveyId,
    showRulesV2Editor,
    rulesV2DisabledReason,
    newFeatureFlagUrl,
}: FeatureFlagsSceneMenuBarProps): JSX.Element {
    const { setActiveGroup } = useActions(maxLogic({ panelId: SIDE_PANEL_PANEL_ID }))
    const { openSidePanel } = useActions(sidePanelLogic)
    const createDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.FeatureFlag, AccessControlLevel.Editor) ?? undefined

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            type: 'submenu',
            id: `${RESOURCE_TYPE}-menubar-new`,
            label: 'New feature flag',
            icon: <IconPlusSmall />,
            disabledReason: createDisabledReason,
            items: [
                {
                    id: `${RESOURCE_TYPE}-menubar-new-feature-flag`,
                    label: 'Feature flag',
                    icon: <IconPlusSmall />,
                    shortcut: <RenderKeybind keybind={[keyBinds.new]} minimal />,
                    onSelect: () => router.actions.push(newFeatureFlagUrl),
                },
                ...(showRulesV2Editor
                    ? [
                          {
                              id: `${RESOURCE_TYPE}-menubar-new-rules-v2-flag`,
                              label: 'Rules v2 flag',
                              icon: <IconFlag />,
                              disabledReason: rulesV2DisabledReason ?? undefined,
                              onSelect: () => router.actions.push(urls.featureFlagNew({ format: 'rules_v2' })),
                          },
                      ]
                    : []),
                ...TEMPLATES.map((template) => {
                    const metadata = TEMPLATE_METADATA[template]
                    return {
                        id: `${RESOURCE_TYPE}-menubar-new-${template}`,
                        label: metadata.name,
                        icon: <metadata.icon />,
                        keywords: [metadata.description],
                        onSelect: () => router.actions.push(urls.featureFlagNew({ template })),
                    }
                }),
                {
                    id: `${RESOURCE_TYPE}-menubar-new-remote-config`,
                    label: 'Remote config',
                    icon: <IconCode />,
                    onSelect: () => router.actions.push(urls.featureFlagNew({ type: 'remote_config' })),
                },
                {
                    id: `${RESOURCE_TYPE}-menubar-new-experiment`,
                    label: 'Experiment',
                    icon: <IconFlask />,
                    onSelect: () => {
                        void addProductIntentForCrossSell({
                            from: ProductKey.FEATURE_FLAGS,
                            to: ProductKey.EXPERIMENTS,
                            intent_context: ProductIntentContext.EXPERIMENT_CREATED,
                        })
                        router.actions.push(urls.experiment('new'))
                    },
                },
                {
                    id: `${RESOURCE_TYPE}-menubar-new-ask-ai`,
                    label: 'Ask AI',
                    icon: <IconSparkles />,
                    opensFloatingUi: true,
                    onSelect: () => {
                        setActiveGroup(
                            createSuggestionGroup(
                                AI_TOOL_DEFINITION.name,
                                React.createElement(IconWrench),
                                AI_SUGGESTIONS
                            )
                        )
                        openSidePanel(SidePanelTab.Max, 'Create a feature flag for ')
                    },
                },
            ],
            pinned: {
                order: 1,
                variant: 'primary',
                render: () => (
                    <ButtonGroup>
                        <Shortcut
                            name="NewFeatureFlag"
                            keybind={[keyBinds.new]}
                            intent="New feature flag"
                            interaction="click"
                            scope={Scene.FeatureFlags}
                            disabledReason={createDisabledReason}
                        >
                            <Button
                                variant="primary"
                                render={<LinkPrimitive to={newFeatureFlagUrl} />}
                                disabledReason={createDisabledReason}
                                tooltip="New feature flag"
                                data-attr="new-feature-flag"
                            >
                                <IconPlus />
                                New
                            </Button>
                        </Shortcut>
                        <QuillNewFeatureFlagMenu
                            disabledReason={createDisabledReason}
                            showRulesV2Editor={showRulesV2Editor}
                            rulesV2DisabledReason={rulesV2DisabledReason}
                        />
                    </ButtonGroup>
                ),
            },
        },
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-feedback`,
            label: 'Feedback',
            icon: <IconMessage />,
            opensFloatingUi: true,
            tooltip: 'Have any questions or feedback?',
            onSelect: () =>
                posthog.displaySurvey(feedbackSurveyId, {
                    displayType: DisplaySurveyType.Popover,
                    ignoreConditions: true,
                    ignoreDelay: true,
                }),
            pinned: {
                order: 1,
                variant: 'secondary',
                render: () => (
                    <FeedbackSurveyButton surveyId={feedbackSurveyId} data-attr="feature-flags-feedback-button" />
                ),
            },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
