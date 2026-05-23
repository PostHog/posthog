import { act, cleanup, render } from '@testing-library/react'
import React, { useEffect } from 'react'

import { setupJsdom } from '../../testing'
import { useChartCanvas } from './useChartCanvas'

const MARGINS = { top: 0, right: 0, bottom: 0, left: 0 }

interface HarnessState {
    ctx: CanvasRenderingContext2D | null
    overlayCtx: CanvasRenderingContext2D | null
    dimensions: { width: number; height: number } | null
}

function Harness({
    withOverlay,
    onState,
}: {
    withOverlay: boolean
    onState: (s: HarnessState) => void
}): React.ReactElement {
    const { wrapperRef, canvasRef, overlayCanvasRef, ctx, overlayCtx, dimensions } = useChartCanvas({
        margins: MARGINS,
    })
    useEffect(() => {
        onState({ ctx, overlayCtx, dimensions })
    }, [ctx, overlayCtx, dimensions, onState])
    return (
        <div ref={wrapperRef}>
            <canvas ref={canvasRef} />
            {withOverlay ? <canvas ref={overlayCanvasRef} /> : null}
        </div>
    )
}

describe('useChartCanvas', () => {
    let teardown: (() => void) | null = null

    beforeEach(() => {
        teardown = setupJsdom()
    })

    afterEach(() => {
        cleanup()
        teardown?.()
        teardown = null
    })

    it.each([
        { label: 'overlay canvas mounted', withOverlay: true, expectOverlayCtxNull: false },
        { label: 'overlay canvas missing', withOverlay: false, expectOverlayCtxNull: true },
    ])('resolves ctx + dimensions when $label', ({ withOverlay, expectOverlayCtxNull }) => {
        const states: HarnessState[] = []
        act(() => {
            render(<Harness withOverlay={withOverlay} onState={(s) => states.push(s)} />)
        })

        const last = states.at(-1)!
        expect(last.ctx).not.toBeNull()
        expect(last.dimensions).not.toBeNull()
        expect(last.overlayCtx === null).toBe(expectOverlayCtxNull)
    })
})
