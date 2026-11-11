import { FEATURE_FLAGS } from 'lib/constants'

import {
    createAccountViewContent,
    createAccountViewComponentInstance,
    parseAccountViewContent,
} from '../../scenes/CustomerAnalyticsAccountScene/accountViewDocument'
import {
    DOT_MATRIX_CONFIG_MAX_BYTES,
    getDotMatrixConfigBytes,
    getDotMatrixTileConfig,
} from '../ProductActivity/dotMatrixTileConfig'
import { listAvailableAccountViewComponents } from './accountViewComponents'

describe('dot matrix tile config', () => {
    it.each([4, 6, 26])('keeps independently configured tiles through a saved round-trip (%s weeks)', (weeks) => {
        const first = { mode: 'dots', weeks, selectedSeries: ['replay'] }
        const second = {
            mode: 'count',
            weeks: 26,
            selectedSeries: ['metric-one', 'metric-two'],
            source: { kind: 'hogql', query: 'SELECT 1', mapping: { row: 'person', column: 'week', value: 'total' } },
        }
        const tiles = parseAccountViewContent(
            createAccountViewContent([
                { nodeId: 'first-matrix', kind: 'dot_matrix', span: 12, config: first },
                { nodeId: 'second-matrix', kind: 'dot_matrix', span: 6, config: second },
            ])
        )
        expect(tiles.map(({ config }) => getDotMatrixTileConfig(config))).toEqual([first, second])
    })

    it.each([
        undefined,
        { dataset: 'production', mode: 'users', weeks: 3, selectedSeries: null },
        { weeks: 27 },
        { weeks: 4.5 },
        { weeks: '6' },
        { selectedSeries: ['valid', 1] },
        { selectedSeries: [''] },
        { selectedSeries: ['x'.repeat(129)] },
        { selectedSeries: Array.from({ length: 65 }, (_, index) => String(index)) },
    ])('uses safe defaults for malformed saved config (%s)', (config) => {
        expect(getDotMatrixTileConfig(config)).toEqual({ mode: 'dots', weeks: 8, selectedSeries: [] })
    })

    it('keeps new tiles unconfigured through a save and blocks malformed sources', () => {
        const tile = createAccountViewComponentInstance('dot_matrix')
        const [restored] = parseAccountViewContent(createAccountViewContent([tile]))
        expect(getDotMatrixTileConfig(restored.config).source).toBeNull()
        expect(
            getDotMatrixTileConfig({ source: { kind: 'hogql', query: 'SELECT 1', mapping: { row: 'person' } } }).source
        ).toBeNull()
        expect(getDotMatrixTileConfig({}).source).toBeUndefined()
    })

    it('keeps valid selections in order and removes duplicates from older configs', () => {
        expect(
            getDotMatrixTileConfig({
                dataset: 'product_activity',
                mode: 'count',
                selectedSeries: ['logs', 'tracing', 'logs'],
            })
        ).toEqual({
            mode: 'count',
            weeks: 8,
            selectedSeries: ['logs', 'tracing'],
        })
    })

    it('offers the tile only while its feature flag is enabled', () => {
        expect(listAvailableAccountViewComponents({}).some(({ kind }) => kind === 'dot_matrix')).toBe(false)
        expect(
            listAvailableAccountViewComponents({ [FEATURE_FLAGS.CUSTOMER_ANALYTICS_DOT_MATRIX]: true }).find(
                ({ kind }) => kind === 'dot_matrix'
            )
        ).toMatchObject({
            tagName: 'DotMatrix',
            label: 'Dot matrix',
        })
    })

    it('measures config size the way the backend does, with non-ASCII characters escaped', () => {
        // len(json.dumps(config, separators=(",", ":")).encode()) in Python gives 57 for this object.
        expect(getDotMatrixConfigBytes({ a: 'é', b: '😀', c: '\x7f', d: '"\n' })).toBe(57)
        expect(DOT_MATRIX_CONFIG_MAX_BYTES).toBe(16_384)
    })

    it('keeps an optional user column in the saved mapping', () => {
        const source = {
            kind: 'hogql',
            query: 'SELECT 1',
            mapping: { row: 'r', column: 'c', series: 's', user: 'who' },
        }
        expect(getDotMatrixTileConfig({ source }).source).toEqual(source)
    })
})
