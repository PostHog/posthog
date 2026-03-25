import { select } from 'd3'
import flamegraph from 'd3-flame-graph'
import { useEffect, useMemo, useRef } from 'react'

import { IconCopy } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

interface FlamegraphNode {
    name: string
    value: number
    children: FlamegraphNode[]
}

function parseFoldedStacks(foldedStacks: string[]): FlamegraphNode {
    const root: FlamegraphNode = { name: 'root', value: 0, children: [] }

    for (const line of foldedStacks) {
        const lastSpace = line.lastIndexOf(' ')
        if (lastSpace === -1) {
            continue
        }
        const stackStr = line.substring(0, lastSpace)
        const count = parseInt(line.substring(lastSpace + 1), 10)
        if (isNaN(count)) {
            continue
        }

        const frames = stackStr.split(';')
        let current = root
        for (const frame of frames) {
            let child = current.children.find((c) => c.name === frame)
            if (!child) {
                child = { name: frame, value: 0, children: [] }
                current.children.push(child)
            }
            child.value += count
            current = child
        }
        root.value += count
    }

    return root
}

export function FlamegraphViewer({ foldedStacks }: { foldedStacks: string[] }): JSX.Element {
    const containerRef = useRef<HTMLDivElement>(null)
    const root = useMemo(() => parseFoldedStacks(foldedStacks), [foldedStacks])

    useEffect(() => {
        if (!containerRef.current || !foldedStacks.length) {
            return
        }

        const container = containerRef.current
        container.innerHTML = ''

        const chart = flamegraph()
            .width(container.clientWidth)
            .cellHeight(18)
            .transitionDuration(250)
            .selfValue(false)
            .inverted(false)
            .tooltip(true)
            .setColorHue('orange')

        select(container).datum(root).call(chart)

        return () => {
            chart.destroy()
        }
    }, [root])

    if (!foldedStacks.length) {
        return <LemonBanner type="info">No profiling data. The query may have been too fast to sample.</LemonBanner>
    }

    return (
        <div className="space-y-2">
            <div className="flex justify-end">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconCopy />}
                    onClick={() => void copyToClipboard(foldedStacks.join('\n'), 'folded stacks')}
                    tooltip="Paste into speedscope.app for an interactive flamegraph"
                >
                    Copy folded stacks
                </LemonButton>
            </div>
            <div ref={containerRef} className="w-full overflow-x-auto" />
        </div>
    )
}
