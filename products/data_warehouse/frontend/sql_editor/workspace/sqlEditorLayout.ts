/**
 * The arrangement of the quill SQL editor's regions, kept as data so people can rearrange the
 * workspace without the view hard-coding one layout. The view renders whatever this describes.
 */

export type SqlEditorInspectorTab = 'schema' | 'variables' | 'history'
export type SqlEditorInspectorSide = 'left' | 'right'
export type SqlEditorResultsPlacement = 'below' | 'beside'

export interface SqlEditorLayout {
    version: 1
    inspector: {
        side: SqlEditorInspectorSide
        open: boolean
        /** Tabs in display order. A tab missing from the list is hidden. */
        tabs: SqlEditorInspectorTab[]
        activeTab: SqlEditorInspectorTab
    }
    results: {
        placement: SqlEditorResultsPlacement
    }
}

export const SQL_EDITOR_INSPECTOR_TABS: readonly SqlEditorInspectorTab[] = ['schema', 'variables', 'history']

export const DEFAULT_SQL_EDITOR_LAYOUT: SqlEditorLayout = {
    version: 1,
    inspector: {
        // The app's navigation rail and its pane sit on the left, so the inspector takes the
        // other edge and the editor never ends up as the fourth column from the left.
        side: 'right',
        open: true,
        tabs: ['schema', 'variables', 'history'],
        activeTab: 'schema',
    },
    results: {
        placement: 'below',
    },
}

function isInspectorTab(value: unknown): value is SqlEditorInspectorTab {
    return typeof value === 'string' && (SQL_EDITOR_INSPECTOR_TABS as readonly string[]).includes(value)
}

export function normalizeSqlEditorLayout(raw: unknown): SqlEditorLayout {
    if (!raw || typeof raw !== 'object') {
        return DEFAULT_SQL_EDITOR_LAYOUT
    }
    const value = raw as Partial<SqlEditorLayout>
    const inspector: Partial<SqlEditorLayout['inspector']> =
        value.inspector && typeof value.inspector === 'object' ? value.inspector : {}
    const results: Partial<SqlEditorLayout['results']> =
        value.results && typeof value.results === 'object' ? value.results : {}

    const tabs = Array.isArray(inspector.tabs)
        ? Array.from(new Set(inspector.tabs.filter(isInspectorTab)))
        : DEFAULT_SQL_EDITOR_LAYOUT.inspector.tabs
    // An inspector with no tabs has nothing to show, so it keeps at least the schema.
    const visibleTabs = tabs.length > 0 ? tabs : DEFAULT_SQL_EDITOR_LAYOUT.inspector.tabs
    const activeTab =
        isInspectorTab(inspector.activeTab) && visibleTabs.includes(inspector.activeTab)
            ? inspector.activeTab
            : visibleTabs[0]

    return {
        version: 1,
        inspector: {
            side: inspector.side === 'left' || inspector.side === 'right' ? inspector.side : 'right',
            open: typeof inspector.open === 'boolean' ? inspector.open : true,
            tabs: visibleTabs,
            activeTab,
        },
        results: {
            placement:
                results.placement === 'below' || results.placement === 'beside'
                    ? results.placement
                    : DEFAULT_SQL_EDITOR_LAYOUT.results.placement,
        },
    }
}

export function setInspectorTabVisible(
    layout: SqlEditorLayout,
    tab: SqlEditorInspectorTab,
    visible: boolean
): SqlEditorLayout {
    const without = layout.inspector.tabs.filter((existing) => existing !== tab)
    if (!visible && without.length === 0) {
        return layout
    }
    const tabs = visible
        ? SQL_EDITOR_INSPECTOR_TABS.filter((candidate) => candidate === tab || without.includes(candidate))
        : without
    return normalizeSqlEditorLayout({
        ...layout,
        inspector: { ...layout.inspector, tabs },
    })
}

export function moveInspectorTab(
    layout: SqlEditorLayout,
    tab: SqlEditorInspectorTab,
    toIndex: number
): SqlEditorLayout {
    const from = layout.inspector.tabs.indexOf(tab)
    if (from === -1) {
        return layout
    }
    const tabs = [...layout.inspector.tabs]
    tabs.splice(from, 1)
    tabs.splice(Math.max(0, Math.min(toIndex, tabs.length)), 0, tab)
    return { ...layout, inspector: { ...layout.inspector, tabs } }
}

export function openInspectorTab(layout: SqlEditorLayout, tab: SqlEditorInspectorTab): SqlEditorLayout {
    const withTab = layout.inspector.tabs.includes(tab) ? layout : setInspectorTabVisible(layout, tab, true)
    return { ...withTab, inspector: { ...withTab.inspector, open: true, activeTab: tab } }
}
