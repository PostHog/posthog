import { FEATURE_FLAGS } from 'lib/constants'

import {
    createAccountViewContent,
    parseAccountViewContent,
} from '../../scenes/CustomerAnalyticsAccountScene/accountViewDocument'
import { listAvailableAccountViewComponents } from './accountViewComponents'
import { getDotMatrixTileConfig } from './dotMatrixTileConfig'

describe('dot matrix tile config', () => {
    it('keeps independently configured tiles through the saved document round-trip', () => {
        const first = { dataset: 'people', mode: 'dots', selectedSeries: ['replay'] }
        const second = { dataset: 'ci', mode: 'count', selectedSeries: ['job-0', 'job-1'] }
        const tiles = parseAccountViewContent(
            createAccountViewContent([
                { nodeId: 'people-matrix', kind: 'dot_matrix', span: 12, config: first },
                { nodeId: 'ci-matrix', kind: 'dot_matrix', span: 6, config: second },
            ])
        )
        expect(tiles.map(({ config }) => getDotMatrixTileConfig(config))).toEqual([first, second])
    })

    it.each([
        undefined,
        { dataset: 'production', mode: 'users', selectedSeries: null },
        { selectedSeries: ['valid', 1] },
        { selectedSeries: [''] },
        { selectedSeries: ['x'.repeat(129)] },
        { selectedSeries: Array.from({ length: 65 }, (_, index) => String(index)) },
    ])('uses safe defaults for malformed saved config (%s)', (config) => {
        expect(getDotMatrixTileConfig(config)).toEqual({ dataset: 'people', mode: 'dots', selectedSeries: [] })
    })

    it('keeps valid selections in order and removes duplicates from older configs', () => {
        expect(
            getDotMatrixTileConfig({
                dataset: 'product_activity',
                mode: 'count',
                selectedSeries: ['logs', 'tracing', 'logs'],
            })
        ).toEqual({
            dataset: 'product_activity',
            mode: 'count',
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
})
