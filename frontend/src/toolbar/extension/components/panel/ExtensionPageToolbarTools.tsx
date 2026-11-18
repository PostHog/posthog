import { useActions, useMountedLogic, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconExternal, IconX } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'

import { SelectorCountContext, SelectorMatchCounter } from '~/toolbar/shared/actions/SelectorCountContext'

import { extensionPageToolbarConnectionLogic } from '../../logics/panel/extensionPageToolbarConnectionLogic'
import { extensionPanelLogic } from '../../logics/panel/extensionPanelLogic'
import { ExtensionActionEditor } from '../actions/ExtensionActionEditor'
import { ExtensionActionsList } from '../actions/ExtensionActionsList'
import { ExtensionEventsMenu } from '../debug/ExtensionEventsMenu'
import { ExtensionInspectedElement } from '../elements/ExtensionInspectedElement'
import { ExtensionExperimentEditor } from '../experiments/ExtensionExperimentEditor'
import { ExtensionExperimentsList } from '../experiments/ExtensionExperimentsList'
import { ExtensionFlagsMenu } from '../flags/ExtensionFlagsMenu'
import { ExtensionMoreMenu } from '../more/ExtensionMoreMenu'
import { ExtensionHeatmapMenu } from '../stats/ExtensionHeatmapMenu'
import { ExtensionWebVitalsMenu } from '../web-vitals/ExtensionWebVitalsMenu'
import { PAGE_TOOLS, PageToolDefinition, PageToolMode } from './extensionPageTools'
import { ExtensionToolHint } from './ExtensionToolHint'
import { usePageToolDisabledReason } from './usePageToolDisabledReason'

function ToolBody({ mode }: { mode: PageToolMode }): JSX.Element {
    const { selectedActionId, selectedExperimentId } = useValues(extensionPageToolbarConnectionLogic)

    switch (mode) {
        case 'inspect':
            return (
                <>
                    <div className="text-xs text-secondary">
                        Click an element to keep it selected. Press Esc to stop.
                    </div>
                    <ExtensionInspectedElement />
                </>
            )
        case 'heatmap':
            return <ExtensionHeatmapMenu />
        case 'actions':
            return selectedActionId !== null ? <ExtensionActionEditor /> : <ExtensionActionsList />
        case 'flags':
            return <ExtensionFlagsMenu />
        case 'events':
            return <ExtensionEventsMenu />
        case 'web-vitals':
            return <ExtensionWebVitalsMenu />
        case 'experiments':
            return selectedExperimentId !== null ? <ExtensionExperimentEditor /> : <ExtensionExperimentsList />
        case 'more':
            return <ExtensionMoreMenu />
    }
}

function ToolHeader({ tool }: { tool: PageToolDefinition }): JSX.Element {
    const { openFeature } = useActions(extensionPanelLogic)
    const { setMode } = useActions(extensionPageToolbarConnectionLogic)
    const { feature } = tool

    return (
        <div className="flex items-start gap-1">
            <div className="flex min-w-0 flex-1 flex-col">
                <h3 className="m-0 truncate text-sm font-semibold">{tool.label}</h3>
                <p className="m-0 text-xs text-secondary">{tool.description}</p>
            </div>
            {feature && (
                <LemonButton
                    size="xsmall"
                    icon={<IconExternal />}
                    tooltip={`Open ${tool.label.toLowerCase()} in PostHog`}
                    onClick={() => openFeature(feature.key, feature.path)}
                    data-attr={`toolbar-extension-feature-${feature.key}`}
                />
            )}
            <LemonButton
                size="xsmall"
                icon={<IconX />}
                tooltip={`Close ${tool.label.toLowerCase()}`}
                onClick={() => setMode('none')}
                data-attr="toolbar-extension-close-tool"
            />
        </div>
    )
}

export function ExtensionPageToolbarTools(): JSX.Element {
    useMountedLogic(extensionPageToolbarConnectionLogic)
    const { mode, connectionStatus, selectorCounter } = useValues(extensionPageToolbarConnectionLogic)
    const { setMode, connectPage, requestSelectorCount } = useActions(extensionPageToolbarConnectionLogic)
    const disabledReason = usePageToolDisabledReason()
    const activeTool = PAGE_TOOLS.find((tool) => tool.mode === mode)
    const [hoveredMode, setHoveredMode] = useState<PageToolMode | null>(null)
    const [focusedMode, setFocusedMode] = useState<PageToolMode | null>(null)
    const hintTool = PAGE_TOOLS.find((tool) => tool.mode === (hoveredMode ?? focusedMode)) ?? null
    // The page counts selector matches for every editor in the panel.
    const counter = useMemo<SelectorMatchCounter>(
        () => ({ count: selectorCounter.count, request: requestSelectorCount }),
        [selectorCounter, requestSelectorCount]
    )

    return (
        <SelectorCountContext.Provider value={counter}>
            <div className="flex flex-1 flex-col gap-2">
                <LemonSegmentedButton
                    fullWidth
                    size="small"
                    value={activeTool?.mode}
                    onChange={(toolMode) => setMode(toolMode === mode ? 'none' : toolMode)}
                    onOptionHover={setHoveredMode}
                    onOptionFocus={setFocusedMode}
                    options={PAGE_TOOLS.map((tool) => ({
                        value: tool.mode,
                        icon: tool.icon,
                        tooltip: activeTool ? tool.label : undefined,
                        disabledReason: disabledReason(tool) ?? undefined,
                        'data-attr': `toolbar-extension-mode-${tool.mode}`,
                    }))}
                />
                {connectionStatus === 'failed' ? (
                    <LemonBanner
                        type="warning"
                        action={{
                            children: 'Try again',
                            onClick: connectPage,
                            'data-attr': 'toolbar-extension-reconnect',
                        }}
                    >
                        The extension couldn't reach this page. Reload the page and try again.
                    </LemonBanner>
                ) : activeTool ? (
                    <>
                        <ToolHeader tool={activeTool} />
                        <ToolBody mode={activeTool.mode} />
                    </>
                ) : (
                    <ExtensionToolHint tool={hintTool} />
                )}
            </div>
        </SelectorCountContext.Provider>
    )
}
