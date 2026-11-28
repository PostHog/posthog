import { definePanelSpec } from '../core/panelSpec'
import { CUSTOM_PANEL_SIZE, customSpec, defineContentPackage } from './customSpec'

describe('customSpec', () => {
    const wide = { w: 24, h: 6, minW: 12, minH: 4 }
    const Component = (): null => null
    const spec = definePanelSpec(
        customSpec(
            [
                defineContentPackage('test', {
                    banner: { Component, size: wide, showOnInteractiveOnly: true, movable: true },
                    plain: { Component },
                }),
            ],
            []
        )
    )

    it.each([
        { content: 'test/banner', size: wide, showOnInteractiveOnly: true, movable: true },
        { content: 'test/plain', size: CUSTOM_PANEL_SIZE, showOnInteractiveOnly: false, movable: false },
        { content: 'test/missing', size: CUSTOM_PANEL_SIZE, showOnInteractiveOnly: false, movable: true },
    ])('reads the size and flags of $content content', ({ content, size, showOnInteractiveOnly, movable }) => {
        const panel = { type: 'custom', config: { content } }
        expect(spec.sizeOf(panel)).toEqual(size)
        expect(spec.showOnInteractiveOnly(panel)).toBe(showOnInteractiveOnly)
        expect(spec.movable(panel)).toBe(movable)
    })

    it.each(['test/missing', 'banner', 'toString', 'constructor'])(
        'rejects %s, which the host did not pass',
        (content) => {
            expect(spec.configError({ content })).not.toBeNull()
        }
    )

    it('throws when two packages share a namespace', () => {
        expect(() => customSpec([defineContentPackage('test', {}), defineContentPackage('test', {})], [])).toThrow(
            'Two custom content packages use the namespace "test"'
        )
    })
})
