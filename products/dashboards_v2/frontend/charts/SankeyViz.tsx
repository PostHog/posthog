import { SankeyChart, type SankeyLinkInput, type SankeyNodeInput } from '@posthog/quill-charts'

import { useDisplayChartTheme } from '../editor/display'
import { fieldOverride, tooltipFor } from './chartCommon'
import { EmptyData } from './EmptyData'
import type { DataFrame } from './frame'
import type { SankeyOptions as O } from './options'
import type { VizProps } from './registry'

const STEP = /^(\d+)_(.*)$/s

export type Flows = { nodes: SankeyNodeInput[]; links: SankeyLinkInput[]; dropped: number }

export function toFlows(frames: DataFrame[]): Flows | null {
    const f = frames.find(
        (x) => x.fields.filter((y) => y.type === 'string').length >= 2 && x.fields.some((y) => y.type === 'number')
    )
    if (!f) {
        return null
    }
    const [src, dst] = f.fields.filter((y) => y.type === 'string') as [
        DataFrame['fields'][number],
        DataFrame['fields'][number],
    ]
    const val = f.fields.find((y) => y.type === 'number')!
    const sums = new Map<string, { source: string; target: string; value: number }>()
    src.values.forEach((s, i) => {
        const source = String(s ?? ''),
            target = String(dst.values[i] ?? ''),
            v = Number(val.values[i])
        if (!source || !target || source === target || !(v > 0)) {
            return
        }
        const k = `${source}\u0000${target}`
        sums.set(k, { source, target, value: (sums.get(k)?.value ?? 0) + v })
    })
    const next = new Map<string, Set<string>>()
    const reaches = (from: string, to: string): boolean => {
        const seen = new Set<string>(),
            stack = [from]
        while (stack.length) {
            const n = stack.pop()!
            if (n === to) {
                return true
            }
            if (seen.has(n)) {
                continue
            }
            seen.add(n)
            stack.push(...(next.get(n) ?? []))
        }
        return false
    }
    let dropped = 0
    const links: SankeyLinkInput[] = []
    for (const l of [...sums.values()].sort((a, b) => b.value - a.value)) {
        if (reaches(l.target, l.source)) {
            dropped++
            continue
        }
        next.set(l.source, (next.get(l.source) ?? new Set()).add(l.target))
        links.push(l)
    }
    const ids = [...new Set(links.flatMap((l) => [l.source, l.target]))]
    const stepped = ids.every((id) => STEP.test(id))
    const nodes = ids.map((id): SankeyNodeInput => {
        const m = stepped ? STEP.exec(id) : null
        return m ? { id, label: m[2]!, column: Number(m[1]) - 1 } : { id }
    })
    return { nodes, links, dropped }
}

export function SankeyViz({ frames, panel, options, onDrill }: VizProps<O>): React.JSX.Element {
    const theme = useDisplayChartTheme()
    const g = toFlows(frames)
    if (!g || !g.links.length) {
        return <EmptyData message="No data: a flow chart needs rows of source, target and a value" />
    }
    const fmt = tooltipFor(panel, panel.fieldConfig?.unit).valueFormatter
    const nodes = g.nodes.map((n) => {
        const o = fieldOverride(panel, n.label ?? n.id)
        return { ...n, ...(o?.displayName ? { label: o.displayName } : {}), ...(o?.color ? { color: o.color } : {}) }
    })
    return (
        <div className="relative flex min-h-0 flex-1 flex-col">
            <SankeyChart
                className="min-h-0 flex-1"
                theme={theme}
                nodes={nodes}
                links={g.links}
                config={{
                    nodeAlign: options.align,
                    showNodeValues: !!options.showValues,
                    valueFormatter: fmt,
                    lastColumnLabels: 'outside',
                }}
                onNodeClick={
                    onDrill
                        ? (n) => onDrill({ refId: frames[0]?.refId, node: n.id, category: n.label, value: n.value })
                        : undefined
                }
                onLinkClick={
                    onDrill
                        ? (l) =>
                              onDrill({
                                  refId: frames[0]?.refId,
                                  node: l.target.id,
                                  category: l.target.label,
                                  value: l.value,
                                  row: { source: l.source.label, target: l.target.label, value: l.value },
                              })
                        : undefined
                }
            />
            {g.dropped > 0 && (
                <div
                    className="absolute bottom-0 right-1 text-[10px] text-muted-foreground"
                    title="The chart draws one-way flows: a link back to an earlier node is left out"
                >
                    {g.dropped} looping link{g.dropped > 1 ? 's' : ''} not drawn
                </div>
            )}
        </div>
    )
}
