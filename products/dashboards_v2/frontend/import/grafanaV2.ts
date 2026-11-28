/**
 * Grafana 12's v2 schema (`elements` + `layout`) in the classic shape, so one converter reads both. Ported from Dash's
 * importer (`fromV2` in `packages/templates/src/grafana.ts`). A tab becomes a row marked `__tab`, which the converter
 * turns into a board tab. Rows inside a row read as "Parent › Child", since a board section holds no rows of its own.
 */

type Json = any // eslint-disable-line @typescript-eslint/no-explicit-any

interface GridPos {
    x: number
    y: number
    w: number
    h: number
}

const VARIABLE_TYPES: Record<string, string> = {
    QueryVariable: 'query',
    CustomVariable: 'custom',
    TextVariable: 'textbox',
    ConstantVariable: 'constant',
    IntervalVariable: 'interval',
    DatasourceVariable: 'datasource',
    AdhocVariable: 'adhoc',
    GroupByVariable: 'groupby',
}

// Grafana's auto grid fits columns to the screen. This assumes a 1600px wide board, in 30px rows with 8px gaps.
const AUTO_GRID_COLUMN_PX: Record<string, number> = { narrow: 192, standard: 320, wide: 480 }
const AUTO_GRID_ROW_PX: Record<string, number> = { short: 168, standard: 320, tall: 512 }

/** The plugin a v2 query or viz config names: `group` in v2beta1, `kind` in v2alpha1, where beta's `kind` is a fixed tag. */
const plugin = (config: Json): string | undefined =>
    config?.group ?? (config?.kind && !['DataQuery', 'VizConfig'].includes(config.kind) ? config.kind : undefined)

export function fromV2(d: Json, warnings: string[]): Json {
    const datasource = (query: Json, alphaDatasource?: Json): Json => {
        const type = plugin(query)
        return type ? { type, uid: query.datasource?.name ?? alphaDatasource?.uid ?? '' } : undefined
    }
    const conditional = (where: string, spec: Json): void => {
        if (spec?.conditionalRendering?.spec?.items?.length) {
            warnings.push(`${where} shows only under a condition in Grafana. Here it always shows.`)
        }
    }
    const panel = (name: string, gridPos: GridPos, item?: Json): Json => {
        const element = d.elements?.[name]
        if (!element) {
            return undefined
        }
        const spec = element.spec ?? {}
        conditional(`Panel "${spec.title ?? name}"`, item)
        if (element.kind === 'LibraryPanel') {
            return { title: spec.title, gridPos, libraryPanel: spec.libraryPanel ?? { name: spec.title } }
        }
        if (element.kind !== 'Panel') {
            warnings.push(`${element.kind} "${name}" isn't supported, so it was left out.`)
            return undefined
        }
        const data = spec.data?.spec ?? {}
        return {
            type: plugin(spec.vizConfig),
            title: spec.title,
            description: spec.description,
            gridPos,
            options: spec.vizConfig?.spec?.options,
            fieldConfig: spec.vizConfig?.spec?.fieldConfig,
            transformations: data.transformations,
            targets: (data.queries ?? []).map((query: Json, index: number) => ({
                ...query.spec?.query?.spec,
                refId: query.spec?.refId ?? query.spec?.query?.spec?.refId ?? String.fromCharCode(65 + index),
                hide: query.spec?.hidden || undefined,
                datasource: datasource(query.spec?.query, query.spec?.datasource),
            })),
        }
    }

    const out: Json[] = []
    let inRow = false
    let groups = 0
    const row = (title: string, y: number, collapsed: boolean, tab?: { group: number; name: string }): void => {
        out.push({
            type: 'row',
            title: title || (tab ? 'Tab' : 'Row'),
            collapsed,
            ...(tab ? { __tab: tab } : {}),
            gridPos: { x: 0, y, w: 24, h: 1 },
        })
        inRow = true
    }
    const lay = (layout: Json, top: number, parent?: string): number => {
        const spec = layout?.spec ?? {}
        if (layout?.kind === 'GridLayout') {
            let bottom = top
            for (const item of spec.items ?? []) {
                const itemSpec = item.spec ?? {}
                if (item.kind === 'GridLayoutRow') {
                    // Early v2 exports kept rows inside the grid, with their items from y 0.
                    row(itemSpec.title, bottom, !!itemSpec.collapsed)
                    bottom = lay({ kind: 'GridLayout', spec: { items: itemSpec.elements } }, bottom + 1)
                    continue
                }
                const y = top + (itemSpec.y ?? 0)
                const h = itemSpec.height ?? 8
                const converted = panel(
                    itemSpec.element?.name,
                    { x: itemSpec.x ?? 0, y, w: itemSpec.width ?? 12, h },
                    itemSpec
                )
                if (converted) {
                    out.push(converted)
                }
                bottom = Math.max(bottom, y + h)
            }
            return bottom
        }
        if (layout?.kind === 'RowsLayout') {
            let y = top
            for (const r of spec.rows ?? []) {
                const rowSpec = r.spec ?? {}
                const title = parent && rowSpec.title ? `${parent} › ${rowSpec.title}` : rowSpec.title || parent
                conditional(`Row "${title}"`, rowSpec)
                const inner = rowSpec.layout?.kind
                if (inner === 'TabsLayout' || inner === 'RowsLayout') {
                    y = lay(rowSpec.layout, y, title)
                    continue
                }
                if (rowSpec.repeat?.value) {
                    warnings.push(
                        `Row "${title}" repeats for each $${rowSpec.repeat.value} in Grafana. Here it shows once.`
                    )
                }
                // A header-less row only works first, before any other row opens.
                if (!(rowSpec.hideHeader && !inRow)) {
                    row(title, y++, !!rowSpec.collapse)
                }
                y = lay(rowSpec.layout, y)
            }
            return y
        }
        if (layout?.kind === 'TabsLayout') {
            const tab = { group: ++groups, name: parent || 'Tabs' }
            let y = top
            for (const t of spec.tabs ?? []) {
                const tabSpec = t.spec ?? {}
                conditional(`Tab "${tabSpec.title}"`, tabSpec)
                row(tabSpec.title, y++, false, tab)
                y = lay(tabSpec.layout, y)
            }
            return y
        }
        if (layout?.kind === 'AutoGridLayout') {
            const columnPx =
                spec.columnWidthMode === 'custom'
                    ? Number(spec.columnWidth) || 320
                    : (AUTO_GRID_COLUMN_PX[spec.columnWidthMode] ?? 320)
            const rowPx =
                spec.rowHeightMode === 'custom'
                    ? Number(spec.rowHeight) || 320
                    : (AUTO_GRID_ROW_PX[spec.rowHeightMode] ?? 320)
            const columns = Math.min(
                Math.max(Number(spec.maxColumnCount) || 3, 1),
                Math.max(1, Math.floor(1600 / columnPx)),
                24
            )
            const w = Math.floor(24 / columns)
            const h = Math.max(2, Math.round((rowPx + 8) / 38))
            ;(spec.items ?? []).forEach((item: Json, n: number) => {
                const converted = panel(
                    item.spec?.element?.name,
                    { x: (n % columns) * w, y: top + Math.floor(n / columns) * h, w, h },
                    item.spec
                )
                if (converted) {
                    out.push(converted)
                }
            })
            return top + Math.ceil((spec.items?.length ?? 0) / columns) * h
        }
        if (layout) {
            warnings.push(`Layout "${layout.kind}" isn't supported, so its panels were left out.`)
        }
        return top
    }
    lay(d.layout, 0)

    const variables = (d.variables ?? []).map((variable: Json) => {
        const spec = variable.spec ?? {}
        return {
            ...spec,
            type: VARIABLE_TYPES[variable.kind] ?? variable.kind,
            ...(variable.kind === 'QueryVariable'
                ? { query: spec.query?.spec ?? spec.definition, datasource: datasource(spec.query) }
                : {}),
        }
    })
    const time = d.timeSettings ?? {}
    return {
        title: d.title,
        description: d.description,
        ...(time.from ? { time: { from: time.from, to: time.to ?? 'now' } } : {}),
        refresh: time.autoRefresh || undefined,
        timezone: time.timezone,
        templating: { list: variables },
        panels: out,
    }
}
