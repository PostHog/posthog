import { z } from 'zod'

import type { MenuAction } from '../../menu/menuAction'
import { definePanelSpec } from '../core/panelSpec'
import { createCustomPanel } from './createCustomPanel'
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
                    copied: { Component, duplicable: true },
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
        { content: 'test/banner', size: wide, flags: true, movable: true, duplicable: false },
        { content: 'test/plain', size: CUSTOM_PANEL_SIZE, flags: false, movable: false, duplicable: false },
        { content: 'test/copied', size: CUSTOM_PANEL_SIZE, flags: false, movable: false, duplicable: true },
        { content: 'test/missing', size: CUSTOM_PANEL_SIZE, flags: false, movable: true, duplicable: true },
    ])('reads the size and flags of $content content', ({ content, size, flags, movable, duplicable }) => {
        const panel = { type: 'custom', config: { content } }
        expect(spec.sizeOf(panel)).toEqual(size)
        expect(spec.showOnInteractiveOnly(panel)).toBe(flags)
        expect(spec.keepMounted(panel)).toBe(flags)
        expect(spec.movable(panel)).toBe(movable)
        expect(spec.duplicable(panel)).toBe(duplicable)
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

    it.each([
        { content: 'plain', keys: [] },
        { content: 'tinted', keys: ['background-color'] },
        { content: 'tintedWithMenu', keys: ['download', 'background-color'] },
        { content: 'keepsAll', keys: ['download', 'background-color'] },
    ])('gives $content content the menu entries $keys', ({ content, keys }) => {
        const keep = (actions: MenuAction[]): MenuAction[] => actions
        const panel = createCustomPanel({
            packages: [
                defineContentPackage('menu', {
                    plain: { Component },
                    tinted: { Component, backgroundColor: true },
                    tintedWithMenu: {
                        Component,
                        backgroundColor: true,
                        menuActions: (actions) => actions.filter((action) => action.key === 'download'),
                    },
                    keepsAll: { Component, backgroundColor: true, menuActions: keep },
                }),
            ],
        })
        const builtIn = ['download', 'background-color'].map(
            (key): MenuAction => ({ key, label: key, dataAttr: key, disabledReason: null })
        )
        const shown = panel.menuActions?.(builtIn, {
            panel: { type: 'custom', config: { content: `menu/${content}` } },
            setConfig: () => {},
            disabledReason: null,
        })
        expect(shown?.map((action) => action.key)).toEqual(keys)
    })

    it('throws when two packages share a namespace', () => {
        expect(() => customSpec([defineContentPackage('test', {}), defineContentPackage('test', {})], [])).toThrow(
            'Two custom content packages use the namespace "test"'
        )
    })
})
