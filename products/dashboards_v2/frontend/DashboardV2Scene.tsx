import './DashboardV2.scss'

import { useActions, useValues } from 'kea'
import { type RefObject, useEffect, useMemo } from 'react'
import { useContainerWidth } from 'react-grid-layout'

import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { SceneExport } from 'scenes/sceneTypes'

import { DashboardV2Actions } from './components/DashboardV2Actions'
import { DashboardV2Tabs } from './components/DashboardV2Tabs'
import { TileGrid } from './components/TileGrid'
import { dashboardV2Logic } from './dashboardV2Logic'
import { stackTiles } from './layout/dashboardEdits'
import { GRID } from './layout/dashboardTypes'

export const scene: SceneExport = {
    component: DashboardV2Scene,
    logic: dashboardV2Logic,
}

export function DashboardV2Scene(): JSX.Element {
    return (
        <FlaggedFeature flag={FEATURE_FLAGS.DASHBOARDS_V2} fallback={<NotFound object="page" />}>
            <DashboardV2 />
        </FlaggedFeature>
    )
}

function isTyping(target: EventTarget | null): boolean {
    return (
        target instanceof Element &&
        !!target.closest('input, textarea, select, [contenteditable="true"], .monaco-editor')
    )
}

function DashboardV2(): JSX.Element {
    const { dashboard, activeTab, canEditLayout } = useValues(dashboardV2Logic)
    const { undo, redo, setStacked } = useActions(dashboardV2Logic)
    const { width, containerRef, mounted } = useContainerWidth()
    const stacked = width > 0 && width < GRID.stackBelowPx
    const tiles = useMemo(
        () => (stacked ? stackTiles(activeTab.tiles, GRID.columns) : activeTab.tiles),
        [stacked, activeTab.tiles]
    )

    useEffect(() => {
        setStacked(stacked)
    }, [stacked, setStacked])

    useEffect(() => {
        if (!canEditLayout) {
            return
        }
        const onKeyDown = (event: KeyboardEvent): void => {
            const key = event.key.toLowerCase()
            if (isTyping(event.target) || !(event.metaKey || event.ctrlKey) || (key !== 'z' && key !== 'y')) {
                return
            }
            event.preventDefault()
            if (key === 'y' || event.shiftKey) {
                redo()
            } else {
                undo()
            }
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [canEditLayout, undo, redo])

    return (
        <div data-quill className="DashboardV2 flex flex-col gap-4 p-4 min-h-full bg-background text-foreground">
            <header className="flex flex-wrap items-center justify-between gap-2">
                <h1 className="text-lg font-semibold m-0">{dashboard.title}</h1>
                <DashboardV2Actions />
            </header>
            <DashboardV2Tabs />
            <div ref={containerRef as RefObject<HTMLDivElement>} className="DashboardV2__canvas">
                {mounted && width > 0 && (
                    <TileGrid
                        key={activeTab.id}
                        gridId={activeTab.id}
                        tiles={tiles}
                        cols={GRID.columns}
                        width={width}
                        editable={canEditLayout}
                    />
                )}
            </div>
        </div>
    )
}
