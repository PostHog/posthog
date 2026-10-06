import { drawSankeyHover, sankeyActiveFlow } from './draw-sankey'
import { computeSankeyLayout } from './sankey-data'

const BACKGROUND = 'hsl(235deg 8% 15%)'

function layoutOf(): ReturnType<typeof computeSankeyLayout> {
    return computeSankeyLayout({
        nodes: [{ id: 'a' }, { id: 'b' }, { id: 'c' }],
        links: [
            { source: 'a', target: 'b', value: 10 },
            { source: 'a', target: 'c', value: 10 },
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

/** Records stroke colors. Like a browser canvas it only accepts colors it can parse. */
function recordingCtx(serialize: Record<string, string>): { ctx: CanvasRenderingContext2D; strokes: string[] } {
    const strokes: string[] = []
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
        save: () => {},
        restore: () => {},
        fillRect: () => {},
        stroke: () => strokes.push(stroke),
    } as unknown as CanvasRenderingContext2D
    return { ctx, strokes }
}

describe('drawSankeyHover', () => {
    it.each([
        ['serialized by the canvas', { [BACKGROUND]: '#202023' }, 2],
        ['rejected by the canvas', {}, 1],
    ])(
        'never paints inactive ribbons in a background d3-color cannot parse: %s',
        (_name, serialize, expectedStrokes) => {
            const layout = layoutOf()
            const { ctx, strokes } = recordingCtx(serialize)
            drawSankeyHover(ctx, layout, sankeyActiveFlow(layout, { kind: 'link', index: 0 }), {
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

    it('leaves a transparent ribbon to the static layer instead of mixing NaN channels', () => {
        const layout = layoutOf()
        layout.links[1].color = 'transparent'
        const { ctx, strokes } = recordingCtx({ [BACKGROUND]: '#202023' })
        drawSankeyHover(ctx, layout, sankeyActiveFlow(layout, { kind: 'link', index: 0 }), {
            linkOpacity: 0.4,
            backgroundColor: BACKGROUND,
            progress: 1,
        })

        expect(strokes).toHaveLength(1)
    })
})
