import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { useCallback, useState } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { themeLogic } from 'lib/logic/themeLogic'
import { urls } from 'scenes/urls'

import { BuiltCanvas } from 'products/canvas/frontend/host/BuiltCanvas'
import {
    canvasHasUserActivation,
    canvasHostLogic,
    handleCanvasDataRequest,
} from 'products/canvas/frontend/host/canvasHostLogic'
import { CanvasHostPromptDialog } from 'products/canvas/frontend/host/CanvasHostPromptDialog'

import { WidgetCardBodyMessage, WidgetCardContent } from '../../components/WidgetCard'
import type { DashboardWidgetComponentProps } from '../registry'
import { patchCanvasAppWidgetConfig } from './canvasAppWidgetConfigValidation'
import { canvasAppWidgetLogic } from './canvasAppWidgetLogic'
import { CanvasPickerSelect } from './CanvasPickerSelect'

export type CanvasAppWidgetResult = {
    canvas: {
        id: string
        name: string
        spaceId: string
        publishedBuildId: string | null
        currentVersionId: string | null
    } | null
    needsConfiguration?: boolean
    canvasNotFound?: boolean
}

function CanvasAppWidgetMessage({
    title,
    message,
    cta,
}: {
    title: string
    message: string
    cta?: JSX.Element
}): JSX.Element {
    return (
        <WidgetCardContent>
            <WidgetCardBodyMessage>
                <div
                    className="flex max-w-xs flex-col items-center gap-2 px-2 text-balance"
                    data-attr="canvas-app-widget-message"
                >
                    <p className="m-0 text-base font-semibold text-primary">{title}</p>
                    <p className="m-0 text-sm text-muted">{message}</p>
                    {cta}
                </div>
            </WidgetCardBodyMessage>
        </WidgetCardContent>
    )
}

function CanvasAppLoadingSkeleton(): JSX.Element {
    return (
        <WidgetCardContent>
            <div className="flex h-full flex-col gap-3 p-2" aria-busy aria-label="Loading canvas">
                <LemonSkeleton className="h-4 w-1/3 max-w-xs" />
                <LemonSkeleton className="h-full min-h-24 w-full" />
            </div>
        </WidgetCardContent>
    )
}

// Editable tile with no canvas chosen yet: owns the optimistic pick so the selection shows
// immediately rather than waiting for the persist + refresh round-trip.
function CanvasAppEmptyStatePicker({
    tileId,
    config,
    onUpdateConfig,
}: Required<Pick<DashboardWidgetComponentProps, 'tileId' | 'config' | 'onUpdateConfig'>>): JSX.Element {
    const [optimisticCanvasId, setOptimisticCanvasId] = useState<string | null>(null)
    return (
        <div className="w-64 max-w-full">
            <CanvasPickerSelect
                pickerKey={`canvas-tile-${tileId}`}
                value={optimisticCanvasId}
                fullWidth
                onChange={async (value) => {
                    setOptimisticCanvasId(value)
                    try {
                        await onUpdateConfig(patchCanvasAppWidgetConfig(config, value))
                    } catch {
                        // Persist failed, drop the optimistic pick so we don't show a selection that wasn't saved.
                        setOptimisticCanvasId((current) => (current === value ? null : current))
                    }
                }}
                dataAttr="canvas-app-widget-empty-state-select"
            />
        </div>
    )
}

/** The live build inside the tile, wired to the same host bridge as the canvas scene. */
function CanvasAppFrame({ artifactUrl, buildId }: { artifactUrl: string; buildId: string | null }): JSX.Element {
    const { capabilities } = useValues(canvasAppWidgetLogic)
    const hostLogic = useMountedLogic(canvasHostLogic)
    const { navigate, openExternal, canvasRendered, canvasErrored } = useActions(hostLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const onDataRequest = useCallback(
        (method: string, payload: unknown) => handleCanvasDataRequest(hostLogic, method, payload),
        [hostLogic]
    )

    return (
        // Keyed by build, so a new build gets a fresh frame and bridge.
        <BuiltCanvas
            key={buildId ?? artifactUrl}
            artifactUrl={artifactUrl}
            capabilities={capabilities}
            theme={isDarkModeOn ? 'dark' : 'light'}
            onDataRequest={onDataRequest}
            onNavigate={navigate}
            onOpenExternal={openExternal}
            onRendered={() => canvasRendered(buildId)}
            onError={(message: string) => canvasErrored(message, buildId)}
            hasUserActivation={canvasHasUserActivation}
            commentHighlights={[]}
            clearTextSelectionKey={0}
        />
    )
}

function CanvasAppTile({ tileId, canvasId }: { tileId: number; canvasId: string }): JSX.Element {
    const logic = canvasAppWidgetLogic({ tileId, canvasId })
    const { renderState, artifactUrl, buildId, hostProps, viewLoading } = useValues(logic)
    const { loadView } = useActions(logic)

    switch (renderState) {
        case 'loading':
            return <CanvasAppLoadingSkeleton />
        case 'error':
            return (
                <WidgetCardContent>
                    <WidgetCardBodyMessage variant="error" onRefresh={loadView} refreshing={viewLoading}>
                        This canvas didn't load. Check your connection and try again.
                    </WidgetCardBodyMessage>
                </WidgetCardContent>
            )
        case 'not-published':
            return (
                <CanvasAppWidgetMessage
                    title="Nothing published yet"
                    message="This canvas has no live build. It appears here once a version is built."
                    cta={
                        <LemonButton type="secondary" size="small" to={urls.canvasDetail(canvasId)} targetBlank>
                            Open canvas
                        </LemonButton>
                    }
                />
            )
        case 'built':
            return (
                <BindLogic logic={canvasAppWidgetLogic} props={{ tileId, canvasId }}>
                    <BindLogic logic={canvasHostLogic} props={{ ...hostProps, surface: 'web_dashboard_widget' }}>
                        <div data-quill className="relative h-full min-h-0 w-full">
                            <CanvasAppFrame artifactUrl={artifactUrl as string} buildId={buildId} />
                            <CanvasHostPromptDialog />
                        </div>
                    </BindLogic>
                </BindLogic>
            )
    }
}

export function CanvasAppWidget({
    tileId,
    config,
    result,
    loading,
    onUpdateConfig,
}: DashboardWidgetComponentProps): JSX.Element {
    const payload = result as CanvasAppWidgetResult | null | undefined

    if (loading && !payload) {
        return <CanvasAppLoadingSkeleton />
    }

    if (!payload || payload.needsConfiguration) {
        return (
            <CanvasAppWidgetMessage
                title="No canvas selected"
                message={
                    onUpdateConfig
                        ? 'Pick a canvas to show it on this dashboard.'
                        : 'No canvas has been selected for this tile yet.'
                }
                cta={
                    onUpdateConfig ? (
                        <CanvasAppEmptyStatePicker tileId={tileId} config={config} onUpdateConfig={onUpdateConfig} />
                    ) : undefined
                }
            />
        )
    }

    if (payload.canvasNotFound || !payload.canvas) {
        return (
            <CanvasAppWidgetMessage
                title="Canvas not available"
                message="You don't have access to this canvas, or it was deleted. Pick another one in the widget settings."
            />
        )
    }

    return <CanvasAppTile tileId={tileId} canvasId={payload.canvas.id} />
}
