import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react'

import type { DashboardAction, DashboardController, RefreshController } from './dashboardContext'

const READ_ONLY = 'This dashboard is read-only'

/** The controller with what a host left out filled in, so the components never check for it. */
export type StableController = Omit<
    DashboardController,
    'activeTabId' | 'disabledReasonFor' | 'onEdit' | 'onActiveTabChange'
> &
    Required<Pick<DashboardController, 'disabledReasonFor' | 'onEdit' | 'onActiveTabChange'>> & {
        activeTabId: string | null
    }

/**
 * Builds the controller from a host's props, so the host can pass inline event handlers and a new `history` or
 * `refresh` object on each render without re-rendering every tile. Functions that decide what renders
 * (`disabledReasonFor`, `tileActions`, `tilePlacementActions`, `dashboardActions`) are used as given, because a new one has to re-render.
 */
export function useStableController(props: DashboardController): StableController {
    const latest = useRef(props)
    useLayoutEffect(() => {
        latest.current = props
    })

    const onEdit = useCallback<StableController['onEdit']>((edit, view) => latest.current.onEdit?.(edit, view), [])
    const [ownTabId, setOwnTabId] = useState(props.activeTabId ?? null)
    const activeTabId = props.onActiveTabChange ? (props.activeTabId ?? null) : ownTabId
    const onActiveTabChange = useCallback(
        (tabId: string) => (latest.current.onActiveTabChange ?? setOwnTabId)(tabId),
        []
    )
    const readOnly = !props.onEdit
    const hostReason = props.disabledReasonFor
    const disabledReasonFor = useMemo(
        () =>
            (action: DashboardAction): string | null =>
                readOnly ? READ_ONLY : (hostReason?.(action) ?? null),
        [readOnly, hostReason]
    )

    const hasHistory = !!props.history
    const canUndo = props.history?.canUndo ?? false
    const canRedo = props.history?.canRedo ?? false
    const history = useMemo(
        () =>
            hasHistory
                ? {
                      canUndo,
                      canRedo,
                      onUndo: () => latest.current.history?.onUndo(),
                      onRedo: () => latest.current.history?.onRedo(),
                  }
                : undefined,
        [hasHistory, canUndo, canRedo]
    )

    const hasRefresh = !!props.refresh
    const { initialInterval, refreshing } = props.refresh ?? {}
    // Compared by value, so a host can write the intervals inline.
    const intervalsKey = props.refresh?.intervals?.join(',')
    const refresh = useMemo<RefreshController | undefined>(
        () =>
            hasRefresh
                ? {
                      intervals: intervalsKey?.split(',').filter(Boolean).map(Number),
                      initialInterval,
                      refreshing,
                      onRefresh: () => latest.current.refresh?.onRefresh?.(),
                  }
                : undefined,
        [hasRefresh, intervalsKey, initialInterval, refreshing]
    )

    const { dashboard, panels, tileActions, tilePlacementActions, dashboardActions, filters, timeRange } = props
    return useMemo(
        () => ({
            dashboard,
            activeTabId,
            panels,
            disabledReasonFor,
            onEdit,
            onActiveTabChange,
            tileActions,
            tilePlacementActions,
            dashboardActions,
            refresh,
            filters,
            timeRange,
            history,
        }),
        [
            dashboard,
            activeTabId,
            panels,
            disabledReasonFor,
            onEdit,
            onActiveTabChange,
            tileActions,
            tilePlacementActions,
            dashboardActions,
            refresh,
            filters,
            timeRange,
            history,
        ]
    )
}
