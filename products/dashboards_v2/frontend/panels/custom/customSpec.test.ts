import { z } from 'zod'

import { definePanelSpec } from '../core/panelSpec'
import { CUSTOM_PANEL_SIZE, customSpec, defineContent, defineContentPackage } from './customSpec'

describe('customSpec', () => {
    const wide = { w: 24, h: 6, minW: 12, minH: 4 }
    const Component = (): null => null
    const spec = definePanelSpec(
        customSpec(
            [
                defineContentPackage('test', {
                    banner: { Component, size: wide, showOnInteractiveOnly: true, movable: true, keepMounted: true },
                    plain: { Component },
                    service: defineContent({
                        Component,
                        propsSchema: z.strictObject({ service: z.string(), limit: z.int().optional() }),
                    }),
                }),
            ],
            []
        )
    )

    it.each([
        { content: 'test/banner', size: wide, flags: true, movable: true },
        { content: 'test/plain', size: CUSTOM_PANEL_SIZE, flags: false, movable: false },
        { content: 'test/missing', size: CUSTOM_PANEL_SIZE, flags: false, movable: true },
    ])('reads the size and flags of $content content', ({ content, size, flags, movable }) => {
        const panel = { type: 'custom', config: { content } }
        expect(spec.sizeOf(panel)).toEqual(size)
        expect(spec.showOnInteractiveOnly(panel)).toBe(flags)
        expect(spec.keepMounted(panel)).toBe(flags)
        expect(spec.movable(panel)).toBe(movable)
    })

    it.each([
        { content: 'test/service', props: { service: 'checkout' }, valid: true },
        { content: 'test/service', props: { service: 'checkout', limit: 5 }, valid: true },
        { content: 'test/service', props: { service: 7 }, valid: false },
        { content: 'test/service', props: { service: 'checkout', other: true }, valid: false },
        { content: 'test/service', props: undefined, valid: false },
        { content: 'test/plain', props: undefined, valid: true },
        { content: 'test/plain', props: { service: 'checkout' }, valid: false },
    ])('checks the props $props of $content against its schema', ({ content, props, valid }) => {
        expect(spec.configError({ content, props }) === null).toBe(valid)
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
