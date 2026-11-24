import type { Widget } from '../dashboard/dashboardTypes'
import { applyTileActionFilters } from './applyTileActions'
import type { TileAction } from './tileAction'

const action = (key: string): TileAction => ({ key, label: key, dataAttr: key, disabledReason: null })
const tile = { id: 't1', widget: { type: 'text', config: {} } as unknown as Widget }

describe('applyTileActionFilters', () => {
    it('lets the host remove an action after the widget type added it', () => {
        const result = applyTileActionFilters(
            [action('move'), action('remove')],
            tile,
            (actions) => [...actions, action('open-in-traces')],
            (actions) => actions.filter((entry) => entry.key !== 'remove' && entry.key !== 'open-in-traces')
        )
        expect(result.map((entry) => entry.key)).toEqual(['move'])
    })

    it('gives the host what the widget filter returned', () => {
        const seen: string[][] = []
        applyTileActionFilters(
            [action('remove')],
            tile,
            () => [action('custom')],
            (actions) => {
                seen.push(actions.map((entry) => entry.key))
                return actions
            }
        )
        expect(seen).toEqual([['custom']])
    })

    it('returns the built list unchanged without filters', () => {
        const actions = [action('remove')]
        expect(applyTileActionFilters(actions, tile, undefined, undefined)).toBe(actions)
    })
})
