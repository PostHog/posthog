import { drawSankey, drawSankeyHover, emphasisForHit } from './draw-sankey'
import { computeSankeyLayout } from './sankey-data'

const BACKGROUND = 'hsl(235deg 8% 15%)'

function layoutOf(secondLinkValue = 10): ReturnType<typeof computeSankeyLayout> {
    return computeSankeyLayout({
        nodes: [{ id: 'a' }, { id: 'b' }, { id: 'c' }],
        links: [
            { source: 'a', target: 'b', value: 10 },
            { source: 'a', target: 'c', value: secondLinkValue },
        ],
        plot: { plotLeft: 0, plotTop: 0, plotWidth: 600, plotHeight: 300 },
        nodeWidth: 10,
        nodePadding: 8,
        nodeAlign: 'justify',
        preserveNodeOrder: false,
        colorForLabel: () => '#ff0000',
        resolveColor: (c) => c,
    })
}

/** Records stroke colors and filled rects. Like a browser canvas it only accepts colors it can parse. */
function recordingCtx(serialize: Record<string, string>): {
    ctx: CanvasRenderingContext2D
    strokes: string[]
    strokeAlphas: number[]
    fills: string[]
} {
    const strokes: string[] = []
    const strokeAlphas: number[] = []
    const fills: string[] = []
    const savedAlphas: number[] = []
    let fill = '#000000'
    let stroke = '#000000'
    const ctx = {
        globalAlpha: 1,
        lineWidth: 1,
        get fillStyle(): string {
            return fill
        },
        set fillStyle(value: string) {
            fill = serialize[value] ?? (value.startsWith('#') ? value : fill)
        },
        get strokeStyle(): string {
            return stroke
        },
        set strokeStyle(value: string) {
            stroke = value
        },
        beginPath: () => {},
        moveTo: () => {},
        bezierCurveTo: () => {},
        save: () => savedAlphas.push(ctx.globalAlpha),
        restore: () => {
            ctx.globalAlpha = savedAlphas.pop() ?? 1
        },
        fillRect: () => fills.push(fill),
        stroke: () => {
            strokes.push(stroke)
            strokeAlphas.push(ctx.globalAlpha)
        },
    } as unknown as CanvasRenderingContext2D
    return { ctx, strokes, strokeAlphas, fills }
}

describe('drawSankeyHover', () => {
    it.each([
        ['serialized by the canvas', { [BACKGROUND]: '#202023' }, 10, 2],
        ['rejected by the canvas', {}, 10, 1],
        ['zero-valued inactive ribbon', { [BACKGROUND]: '#202023' }, 0, 1],
    ])(
        'dims an inactive ribbon only when it carries flow and the background parses: %s',
        (_name, serialize, secondLinkValue, expectedStrokes) => {
            const layout = layoutOf(secondLinkValue)
            const { ctx, strokes } = recordingCtx(serialize)
            drawSankeyHover(ctx, layout, emphasisForHit(layout, { kind: 'link', index: 0 }), {
                linkOpacity: 0.4,
                backgroundColor: BACKGROUND,
                progress: 1,
            })

            // A usable background dims the inactive ribbon to an opaque mix; otherwise only the active
            // ribbon is repainted and the static layer keeps the inactive one as it was.
            expect(strokes).toHaveLength(expectedStrokes)
            expect(strokes).not.toContain(BACKGROUND)
            expect(strokes).not.toContain('#202023')
        }
    )

    it('leaves a transparent ribbon and node to the static layer instead of mixing NaN channels', () => {
        const layout = layoutOf()
        layout.links[1].color = 'transparent'
        layout.nodes.find((node) => node.id === 'c')!.color = 'transparent'
        const { ctx, strokes, fills } = recordingCtx({ [BACKGROUND]: '#202023' })
        drawSankeyHover(ctx, layout, emphasisForHit(layout, { kind: 'link', index: 0 }), {
            linkOpacity: 0.4,
            backgroundColor: BACKGROUND,
            progress: 1,
        })

        expect(strokes).toHaveLength(1)
        expect(fills).toHaveLength(2)
    })

    it.each([
        ['static layer below the hover target', 'static', 0.4, 0.85],
        ['hover layer below the hover target', 'hover', 0.4, 0.85],
        ['static layer above the hover target', 'static', 0.9, 0.9],
        ['hover layer above the hover target', 'hover', 0.9, 0.9],
    ])('composites an emphasized ribbon to its target opacity: %s', (_name, layer, linkOpacity, expectedOpacity) => {
        const layout = layoutOf(0)
        const emphasis = emphasisForHit(layout, { kind: 'link', index: 0 })
        const { ctx, strokeAlphas } = recordingCtx({ [BACKGROUND]: '#202023' })
        if (layer === 'static') {
            drawSankey(ctx, layout, { linkOpacity, emphasis, backgroundColor: BACKGROUND })
        } else {
            drawSankeyHover(ctx, layout, emphasis, { linkOpacity, backgroundColor: BACKGROUND, progress: 1 })
        }

        // The hover layer sits on a static layer that already drew the ribbon at rest.
        const painted = layer === 'hover' ? [linkOpacity, ...strokeAlphas] : strokeAlphas
        const composite = 1 - painted.reduce((clear, alpha) => clear * (1 - alpha), 1)
        expect(composite).toBeCloseTo(expectedOpacity)
    })
})
