import { ViewportScaler } from '../viewport-scaler'

function mockContentEl(): HTMLElement {
    return {
        style: {} as CSSStyleDeclaration,
    } as HTMLElement
}

// eslint-disable-next-line @typescript-eslint/explicit-function-return-type
function mockReplayer(iframeWidth: string, iframeHeight: string) {
    const listeners: Record<string, Function[]> = {}
    return {
        iframe: { width: iframeWidth, height: iframeHeight },
        on: jest.fn((event: string, cb: Function) => {
            ;(listeners[event] ||= []).push(cb)
        }),
        _emit: (event: string, data: any) => {
            for (const cb of listeners[event] || []) {
                cb(data)
            }
        },
    }
}

describe('ViewportScaler', () => {
    beforeEach(() => {
        Object.defineProperty(window, 'innerWidth', {
            value: 1920,
            configurable: true,
        })
        Object.defineProperty(window, 'innerHeight', {
            value: 1080,
            configurable: true,
        })
    })

    describe('apply', () => {
        it('scales recording to fit viewport and centers it', () => {
            const el = mockContentEl()
            const scaler = new ViewportScaler(el, 0)

            scaler.apply(1280, 720)

            expect(el.style.width).toBe('1280px')
            expect(el.style.height).toBe('720px')
            expect(el.style.overflow).toBe('hidden')
            expect(el.style.transformOrigin).toBe('top left')
            expect(el.style.transform).toBe('translate(0px, 0px) scale(1.5)')
        })

        it('accounts for footer height', () => {
            const el = mockContentEl()
            const scaler = new ViewportScaler(el, 32)

            scaler.apply(1920, 1080)

            const scale = 1048 / 1080
            const scaledW = 1920 * scale
            const scaledH = 1080 * scale
            const offsetX = (1920 - scaledW) / 2
            const offsetY = (1048 - scaledH) / 2
            expect(el.style.transform).toBe(`translate(${offsetX}px, ${offsetY}px) scale(${scale})`)
        })

        it('skips when dimensions are zero or negative', () => {
            const el = mockContentEl()
            const scaler = new ViewportScaler(el, 0)

            scaler.apply(0, 720)
            expect(el.style.width).toBeUndefined()

            scaler.apply(1280, -1)
            expect(el.style.width).toBeUndefined()
        })

        it('letterboxes when recording is wider than viewport', () => {
            Object.defineProperty(window, 'innerWidth', {
                value: 800,
                configurable: true,
            })
            Object.defineProperty(window, 'innerHeight', {
                value: 600,
                configurable: true,
            })

            const el = mockContentEl()
            const scaler = new ViewportScaler(el, 0)

            scaler.apply(1920, 1080)
            const scale = 800 / 1920
            expect(el.style.transform).toContain(`scale(${scale})`)
        })
    })

    describe('attachToReplayer', () => {
        it('applies initial scale from iframe dimensions', () => {
            const el = mockContentEl()
            const scaler = new ViewportScaler(el, 0)
            const replayer = mockReplayer('1280', '720')

            scaler.attachToReplayer(replayer as any)

            expect(el.style.width).toBe('1280px')
        })

        it('skips initial scale when iframe has zero dimensions', () => {
            const el = mockContentEl()
            const scaler = new ViewportScaler(el, 0)
            const replayer = mockReplayer('0', '0')

            scaler.attachToReplayer(replayer as any)

            expect(el.style.width).toBeUndefined()
        })

        it('rescales on resize events', () => {
            const el = mockContentEl()
            const scaler = new ViewportScaler(el, 0)
            const replayer = mockReplayer('1280', '720')

            scaler.attachToReplayer(replayer as any)
            expect(el.style.width).toBe('1280px')

            replayer._emit('resize', { width: 800, height: 600 })
            expect(el.style.width).toBe('800px')
        })
    })
})
