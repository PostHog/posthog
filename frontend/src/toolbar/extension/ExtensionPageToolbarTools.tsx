import { useActions, useMountedLogic, useValues } from 'kea'
import { useMemo } from 'react'

import { IconExternal, IconX } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'

import { SelectorCountContext, SelectorMatchCounter } from '~/toolbar/actions/SelectorCountContext'

import { ExtensionActionEditor } from './ExtensionActionEditor'
import { ExtensionActionsList } from './ExtensionActionsList'
import { ExtensionEventsMenu } from './ExtensionEventsMenu'
import { ExtensionFeatureList } from './ExtensionFeatureList'
import { ExtensionFlagsMenu } from './ExtensionFlagsMenu'
import { ExtensionHeatmapMenu } from './ExtensionHeatmapMenu'
import { ExtensionInspectedElement } from './ExtensionInspectedElement'
import { ExtensionMoreMenu } from './ExtensionMoreMenu'
import { extensionPageToolbarConnectionLogic } from './extensionPageToolbarConnectionLogic'
import { PAGE_TOOLS, PageToolDefinition, PageToolMode } from './extensionPageTools'
import { extensionPanelLogic } from './extensionPanelLogic'
import { ExtensionWebVitalsMenu } from './ExtensionWebVitalsMenu'
import { usePageToolDisabledReason } from './usePageToolDisabledReason'

type PanelTool = PageToolDefinition & { mode: PageToolMode }

const PANEL_TOOLS = PAGE_TOOLS.filter((tool): tool is PanelTool => !!tool.mode)

function ToolBody({ mode }: { mode: PageToolMode }): JSX.Element {
    const { selectedActionId } = useValues(extensionPageToolbarConnectionLogic)

    switch (mode) {
        case 'inspect':
            return (
                <>
                    <div className="text-xs text-secondary">
                        Hover an element on the page to see its selector and actions, or click it to keep it selected.
                        Press Esc to stop.
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
        case 'more':
            return <ExtensionMoreMenu />
    }
}

function ToolHeader({ tool }: { tool: PanelTool }): JSX.Element {
    const { openFeature } = useActions(extensionPanelLogic)
    const { setMode } = useActions(extensionPageToolbarConnectionLogic)
    const { feature } = tool

    return (
        <div className="flex items-center gap-1">
            <h3 className="m-0 flex-1 truncate text-sm font-semibold">{tool.label}</h3>
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

export function ExtensionPageToolbarTools({ origin }: { origin: string }): JSX.Element {
    useMountedLogic(extensionPageToolbarConnectionLogic)
    const { mode, connectionStatus, selectorCounter } = useValues(extensionPageToolbarConnectionLogic)
    const { setMode, connectPage, requestSelectorCount } = useActions(extensionPageToolbarConnectionLogic)
    const disabledReason = usePageToolDisabledReason()
    const activeTool = PANEL_TOOLS.find((tool) => tool.mode === mode)
    // The page counts selector matches for every editor in the panel.
    const counter = useMemo<SelectorMatchCounter>(
        () => ({ count: selectorCounter.count, request: requestSelectorCount }),
        [selectorCounter, requestSelectorCount]
    )

    return (
        <SelectorCountContext.Provider value={counter}>
            <div className="flex flex-col gap-2">
                <LemonSegmentedButton
                    fullWidth
                    size="small"
                    value={activeTool?.mode}
                    onChange={(toolMode) => setMode(toolMode === mode ? 'none' : toolMode)}
                    options={PANEL_TOOLS.map((tool) => ({
                        value: tool.mode,
                        icon: tool.icon,
                        tooltip: tool.label,
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
                    <>
                        <div className="flex flex-col gap-1">
                            {PANEL_TOOLS.map((tool) => (
                                <LemonButton
                                    key={tool.mode}
                                    fullWidth
                                    icon={tool.icon}
                                    disabledReason={disabledReason(tool)}
                                    onClick={() => setMode(tool.mode)}
                                    data-attr={`toolbar-extension-open-${tool.mode}`}
                                >
                                    <span className="flex min-w-0 flex-col">
                                        <span>{tool.label}</span>
                                        <span className="text-xs font-normal text-secondary whitespace-normal">
                                            {tool.description}
                                        </span>
                                    </span>
                                </LemonButton>
                            ))}
                        </div>
                        <ExtensionFeatureList origin={origin} />
                    </>
                )}
            </div>
        </SelectorCountContext.Provider>
    )
}
