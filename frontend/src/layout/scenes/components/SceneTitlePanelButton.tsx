import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconBrackets, IconSidePanel, IconSparkles, IconWrench } from '@posthog/icons'

import { RenderKeybind } from 'lib/components/Shortcuts/ShortcutMenu'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'
import { UseMaxToolOptions, useMaxTool } from 'scenes/max/useMaxTool'
import { sceneLogic } from 'scenes/sceneLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { todayShellLogic } from '~/layout/today/todayShellLogic'
import { SidePanelTab } from '~/types'

import { sceneLayoutLogic } from '../sceneLayoutLogic'

/**
 * The click on the PostHog AI button is the only proof the handler ran. Every route into the
 * panel captures `sidebar opened` afterwards, so a click without that follow-up event marks a
 * click that never reached `openSidePanel`. Scene id is read off `sceneLogic` without
 * subscribing so capture never triggers a re-render.
 */
function captureSceneAiButtonClicked(tool: string | null): void {
    posthog.capture('scene ai button clicked', {
        scene: sceneLogic.findMounted()?.values.activeSceneId ?? null,
        tool,
    })
}

export function SceneTitlePanelButton({
    maxToolProps,
    buttonClassName = 'size-[33px]',
    maxButtonLabel,
}: {
    maxToolProps?: Omit<UseMaxToolOptions, 'active'>
    buttonClassName?: string
    maxButtonLabel?: string
}): JSX.Element | null {
    const { scenePanelIsPresent } = useValues(sceneLayoutLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { sidePanelOpen } = useValues(sidePanelStateLogic)

    const inactiveMaxToolProps: UseMaxToolOptions = { identifier: 'read_data', active: false }
    const { openMax, definition } = useMaxTool(maxToolProps ? { ...maxToolProps, active: true } : inactiveMaxToolProps)

    const { featureFlags } = useValues(featureFlagLogic)
    const sceneMenuBarEnabled = !!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]
    const { todayRailEnabled, phoneLayout } = useValues(todayShellLogic)

    // Open Info tab if scene has panel content, otherwise default to PostHog AI
    const defaultTab = scenePanelIsPresent ? SidePanelTab.Info : SidePanelTab.Max

    if (sidePanelOpen || (todayRailEnabled && phoneLayout)) {
        return null
    }

    return (
        <>
            {!sceneMenuBarEnabled && !todayRailEnabled && (
                <ButtonPrimitive
                    className={cn(buttonClassName, maxButtonLabel && 'w-auto px-2')}
                    onClick={(e) => {
                        e.stopPropagation()
                        e.preventDefault()
                        captureSceneAiButtonClicked(maxToolProps?.identifier ?? null)
                        if (openMax) {
                            openMax()
                        } else {
                            openSidePanel(SidePanelTab.Max)
                        }
                    }}
                    tooltip={
                        definition ? (
                            <>
                                Open PostHog AI
                                <br />
                                <div className="flex items-center">
                                    {definition.icon || <IconWrench />}
                                    <i className="ml-1.5">{definition.name}</i>
                                </div>
                            </>
                        ) : (
                            'Open PostHog AI'
                        )
                    }
                    tooltipPlacement="bottom-end"
                    tooltipCloseDelayMs={0}
                    iconOnly={!maxButtonLabel}
                    data-attr="open-context-panel-ai-button"
                >
                    <div className="relative">
                        <IconSparkles className="text-ai group-hover/button-primitive:animate-hue-rotate" />
                        {maxToolProps && (
                            <IconBrackets className="absolute size-2.5 top-0 -right-1 text-black dark:text-white" />
                        )}
                    </div>
                    {maxButtonLabel}
                </ButtonPrimitive>
            )}
            {/* Size to mimic lemon button small */}
            <ButtonPrimitive
                className={cn(buttonClassName, 'group -mr-[2px]')}
                onClick={(e) => {
                    e.stopPropagation()
                    e.preventDefault()
                    openSidePanel(defaultTab)
                }}
                tooltip={
                    <>
                        Open context panel
                        <RenderKeybind className="relative -top-px ml-1" keybind={[keyBinds.toggleRightNav]} />
                    </>
                }
                tooltipPlacement="bottom-end"
                tooltipCloseDelayMs={0}
                iconOnly
                data-attr="open-context-panel-button"
            >
                <IconSidePanel className="text-primary group-hover:text-primary z-10" />
            </ButtonPrimitive>
        </>
    )
}
