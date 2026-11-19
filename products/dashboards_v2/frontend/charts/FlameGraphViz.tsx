import { FlameGraph, type FlameNode } from '@posthog/quill-charts'

import { useDisplayChartTheme } from '../editor/display'
import { fieldOverride, tooltipFor } from './chartCommon'
import { EmptyData } from './EmptyData'
import type { DataFrame } from './frame'
import type { FlameGraphOptions as O } from './options'
import type { VizProps } from './registry'

type Tree = { value: number; children: Map<string, Tree> }

function paths(f: DataFrame, separator: string): { path: string[]; value: number }[] {
    const text = f.fields.filter((x) => x.type === 'string')
    const val = f.fields.find((x) => x.type === 'number')
    if (!text.length || !val) {
        return []
    }
    return val.values.flatMap((v, i) => {
        const value = Number(v)
        const path =
            text.length === 1
                ? String(text[0]!.values[i] ?? '')
                      .split(separator)
                      .filter(Boolean)
                : text.map((x) => String(x.values[i] ?? '')).filter(Boolean)
        return path.length && value > 0 ? [{ path, value }] : []
    })
}

const treeOf = (rows: { path: string[]; value: number }[]): Tree => {
    const root: Tree = { value: 0, children: new Map() }
    for (const { path, value } of rows) {
        let n = root
        n.value += value
        for (const name of path) {
            const c = n.children.get(name) ?? { value: 0, children: new Map() }
            n.children.set(name, c)
            c.value += value
            n = c
        }
    }
    return root
}

export function toFlame(frames: DataFrame[], separator = ';'): FlameNode[] | null {
    const now = frames.filter((f) => !f.meta?.previous)
    const cur = now.flatMap((f) => paths(f, separator))
    if (!cur.length) {
        return null
    }
    const before = frames.filter((f) => f.meta?.previous).flatMap((f) => paths(f, separator))
    const base = before.length ? treeOf(before) : undefined
    const convert = (name: string, t: Tree, b: Tree | undefined): FlameNode => ({
        name,
        value: t.value,
        ...(base ? { baselineValue: b?.value ?? 0 } : {}),
        ...(t.children.size ? { children: [...t.children].map(([n, c]) => convert(n, c, b?.children.get(n))) } : {}),
    })
    return [...treeOf(cur).children].map(([n, c]) => convert(n, c, base?.children.get(n)))
}

export function FlameGraphViz({ frames, panel, options, height }: VizProps<O>): React.JSX.Element {
    const theme = useDisplayChartTheme()
    const roots = toFlame(frames, options.separator || ';')
    if (!roots) {
        return (
            <EmptyData message="No data: a flame graph needs rows of text levels (or one text column of a;b;c stacks) and a value" />
        )
    }
    const groupColors = Object.fromEntries(
        roots.flatMap((r) => {
            const c = fieldOverride(panel, r.name)?.color
            return c ? [[r.name, c]] : []
        })
    )
    const withGroups = (n: FlameNode, group: string): FlameNode => ({
        ...n,
        group,
        ...(n.children ? { children: n.children.map((c) => withGroups(c, group)) } : {}),
    })
    return (
        <div className="min-h-0 flex-1 overflow-hidden">
            <FlameGraph
                theme={theme}
                data={Object.keys(groupColors).length ? roots.map((r) => withGroups(r, r.name)) : roots}
                search={options.search || undefined}
                config={{
                    valueFormatter: tooltipFor(panel, panel.fieldConfig?.unit).valueFormatter,
                    maxHeight: Math.max(120, height - 8),
                    ...(Object.keys(groupColors).length ? { groupColors } : {}),
                    ...(options.diffThreshold !== undefined
                        ? { diff: { threshold: options.diffThreshold / 100 } }
                        : {}),
                }}
            />
        </div>
    )
}
