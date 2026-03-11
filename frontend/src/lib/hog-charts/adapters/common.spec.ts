import type { HogChartTheme, Series } from '../types'
import {
    buildGoalLineAnnotations,
    buildScaleConfig,
    buildTooltipContext,
    buildYAxes,
    crosshairConfig,
    incompleteSegment,
    resolvePointRadius,
} from './common'

jest.mock('lib/charts/utils/theme', () => ({
    buildTheme: jest.fn(() => ({
        colors: ['#1d4aff', '#e3a507', '#f46b00'],
        axisColor: '#999',
        gridColor: '#eee',
        crosshairColor: '#aaa',
        tooltipBackground: '#fff',
        tooltipColor: '#000',
    })),
    seriesColor: jest.fn((theme: HogChartTheme, index: number) => theme.colors[index % theme.colors.length]),
}))

jest.mock('lib/charts/utils/format', () => ({
    formatValue: jest.fn((value: number) => String(value)),
}))

function makeTheme(overrides?: Partial<HogChartTheme>): HogChartTheme {
    return {
        colors: ['#1d4aff', '#e3a507', '#f46b00', '#0080ff', '#df7eff'],
        axisColor: '#888',
        gridColor: '#ddd',
        crosshairColor: '#aaa',
        tooltipBackground: '#fff',
        tooltipColor: '#000',
        goalLineColor: '#F04F58',
        tooltipBorderRadius: 8,
        ...overrides,
    }
}

function makeChartBounds(): DOMRect {
    return { x: 0, y: 0, width: 800, height: 400, top: 0, left: 0, bottom: 400, right: 800 } as DOMRect
}

describe('hog-charts adapters/common', () => {
    describe('resolvePointRadius', () => {
        it.each([
            { showDots: true as const, pointCount: 10, expected: 3, label: 'true always returns 3' },
            { showDots: false as const, pointCount: 10, expected: 0, label: 'false always returns 0' },
            { showDots: undefined, pointCount: 1, expected: 4, label: 'auto with 1 point returns 4' },
            { showDots: undefined, pointCount: 30, expected: 3, label: 'auto with <=30 points returns 3' },
            { showDots: undefined, pointCount: 31, expected: 0, label: 'auto with >30 points returns 0' },
        ])('$label', ({ showDots, pointCount, expected }) => {
            expect(resolvePointRadius(showDots, pointCount)).toBe(expected)
        })
    })

    describe('crosshairConfig', () => {
        it('returns disabled crosshair when enabled is false', () => {
            expect(crosshairConfig(false, '#aaa')).toEqual({ crosshair: false })
        })

        it('returns full crosshair config when enabled is true', () => {
            const config = crosshairConfig(true, '#aaa')
            expect(config).toMatchObject({
                crosshair: {
                    snap: { enabled: true },
                    sync: { enabled: false },
                    zoom: { enabled: false },
                    line: { color: '#aaa', width: 1 },
                },
            })
        })
    })

    describe('incompleteSegment', () => {
        it('returns undefined when count is 0 or negative', () => {
            expect(incompleteSegment(10, 0)).toBeUndefined()
            expect(incompleteSegment(10, -1)).toBeUndefined()
        })

        it('returns dashes for points at or after the start index, undefined before', () => {
            const segment = incompleteSegment(10, 3)
            // startIndex = 10 - 3 = 7
            expect(segment!.borderDash({ p1DataIndex: 7 })).toEqual([10, 10])
            expect(segment!.borderDash({ p1DataIndex: 9 })).toEqual([10, 10])
            expect(segment!.borderDash({ p1DataIndex: 6 })).toBeUndefined()
        })
    })

    describe('buildScaleConfig', () => {
        const theme = makeTheme()

        it('axis config takes precedence over defaults', () => {
            const result = buildScaleConfig({ gridLines: false }, theme, { gridLines: true })
            expect((result.grid as { display: boolean }).display).toBe(false)
        })

        it('falls back to defaults when axis config is undefined', () => {
            const result = buildScaleConfig(undefined, theme, { gridLines: true })
            expect((result.grid as { display: boolean }).display).toBe(true)
        })

        it('sets title when label is provided', () => {
            const result = buildScaleConfig({ label: 'My Axis' }, theme)
            expect(result.title).toMatchObject({ display: true, text: 'My Axis' })
        })

        it.each([
            { scale: 'logarithmic' as const, expected: 'logarithmic' },
            { scale: 'linear' as const, expected: 'linear' },
        ])('maps scale "$scale" to Chart.js type', ({ scale, expected }) => {
            expect(buildScaleConfig({ scale }, theme).type).toBe(expected)
        })

        it('sets a tick callback when format is provided', () => {
            const result = buildScaleConfig({ format: 'number' }, theme)
            expect(typeof (result.ticks as { callback: unknown }).callback).toBe('function')
        })
    })

    describe('buildYAxes', () => {
        const theme = makeTheme()

        it('returns single y axis for object or undefined yAxis', () => {
            for (const yAxis of [{ label: 'Count' }, undefined]) {
                const result = buildYAxes({ data: [], labels: [], yAxis }, theme)
                expect(result).toHaveProperty('y')
                expect(result).not.toHaveProperty('y1')
            }
        })

        it('returns dual y axes with correct positions for tuple yAxis', () => {
            const result = buildYAxes({ data: [], labels: [], yAxis: [{}, {}] as [object, object] }, theme) as {
                y: { position: string }
                y1: { position: string; grid: { display: boolean } }
            }
            expect(result.y.position).toBe('left')
            expect(result.y1.position).toBe('right')
            expect(result.y1.grid.display).toBe(false)
        })
    })

    describe('buildGoalLineAnnotations', () => {
        const theme = makeTheme()

        it('returns empty array when goalLines is undefined or empty', () => {
            expect(buildGoalLineAnnotations(undefined, theme)).toEqual([])
            expect(buildGoalLineAnnotations([], theme)).toEqual([])
        })

        it('maps value, scaleID, and falls back to theme color', () => {
            const [annotation] = buildGoalLineAnnotations([{ value: 42 }], theme)
            expect(annotation).toMatchObject({ value: 42, scaleID: 'y', borderColor: theme.goalLineColor })
        })

        it('uses goal line color when provided', () => {
            const [annotation] = buildGoalLineAnnotations([{ value: 10, color: '#ff0000' }], theme)
            expect(annotation.borderColor).toBe('#ff0000')
        })

        it.each([
            { style: 'solid' as const, expectedDash: [] },
            { style: 'dashed' as const, expectedDash: [6, 4] },
            { style: 'dotted' as const, expectedDash: [2, 4] },
            { style: undefined, expectedDash: [6, 4] },
        ])('style "$style" produces borderDash $expectedDash', ({ style, expectedDash }) => {
            const [annotation] = buildGoalLineAnnotations([{ value: 10, style }], theme)
            expect(annotation.borderDash).toEqual(expectedDash)
        })

        it('sets label config when label is provided', () => {
            const [annotation] = buildGoalLineAnnotations([{ value: 10, label: 'Target' }], theme)
            expect(annotation.label).toMatchObject({ display: true, content: 'Target' })
        })
    })

    describe('buildTooltipContext', () => {
        const chartBounds = makeChartBounds()

        function makeTooltipModel(
            overrides?: Partial<Parameters<typeof buildTooltipContext>[0]>
        ): Parameters<typeof buildTooltipContext>[0] {
            return {
                opacity: 1,
                title: ['Jan 1'],
                caretX: 100,
                caretY: 50,
                dataPoints: [
                    {
                        datasetIndex: 0,
                        dataIndex: 2,
                        raw: 42,
                        dataset: { label: 'Series A', borderColor: '#1d4aff' },
                    },
                ],
                ...overrides,
            }
        }

        it('returns null when opacity is 0 or dataPoints is empty/undefined', () => {
            expect(buildTooltipContext(makeTooltipModel({ opacity: 0 }), chartBounds, [])).toBeNull()
            expect(buildTooltipContext(makeTooltipModel({ dataPoints: undefined }), chartBounds, [])).toBeNull()
            expect(buildTooltipContext(makeTooltipModel({ dataPoints: [] }), chartBounds, [])).toBeNull()
        })

        it('maps data points to TooltipPoints with correct fields', () => {
            const result = buildTooltipContext(makeTooltipModel(), chartBounds, [])
            expect(result!.points[0]).toMatchObject({
                seriesIndex: 0,
                pointIndex: 2,
                value: 42,
                seriesLabel: 'Series A',
                color: '#1d4aff',
            })
            expect(result!.label).toBe('Jan 1')
        })

        it('filters out datasets with _hogHideFromTooltip and series with hideFromTooltip', () => {
            const model = makeTooltipModel({
                dataPoints: [
                    { datasetIndex: 0, dataIndex: 0, raw: 10, dataset: { label: 'Visible', borderColor: '#111' } },
                    {
                        datasetIndex: 1,
                        dataIndex: 0,
                        raw: 20,
                        dataset: { label: 'Dataset-hidden', borderColor: '#222', _hogHideFromTooltip: true },
                    },
                    {
                        datasetIndex: 2,
                        dataIndex: 0,
                        raw: 30,
                        dataset: { label: 'Series-hidden', borderColor: '#333' },
                    },
                ],
            })
            const seriesData: Series[] = [
                { label: 'Visible', data: [] },
                { label: 'Dataset-hidden', data: [] },
                { label: 'Series-hidden', data: [], hideFromTooltip: true },
            ]
            const result = buildTooltipContext(model, chartBounds, seriesData)
            expect(result!.points).toHaveLength(1)
            expect(result!.points[0].seriesLabel).toBe('Visible')
        })

        it('resolves color from array borderColor using dataIndex', () => {
            const model = makeTooltipModel({
                dataPoints: [
                    {
                        datasetIndex: 0,
                        dataIndex: 2,
                        raw: 5,
                        dataset: { label: 'A', borderColor: ['#000', '#111', '#222'] },
                    },
                ],
            })
            expect(buildTooltipContext(model, chartBounds, [])!.points[0].color).toBe('#222')
        })

        it('falls back to #888 when borderColor is undefined', () => {
            const model = makeTooltipModel({
                dataPoints: [{ datasetIndex: 0, dataIndex: 0, raw: 5, dataset: { label: 'A' } }],
            })
            expect(buildTooltipContext(model, chartBounds, [])!.points[0].color).toBe('#888')
        })

        it('uses _hogMeta from dataset, falls back to seriesData meta', () => {
            const datasetMeta = { source: 'dataset' }
            const seriesMeta = { source: 'series' }

            const withDatasetMeta = makeTooltipModel({
                dataPoints: [
                    {
                        datasetIndex: 0,
                        dataIndex: 0,
                        raw: 5,
                        dataset: { label: 'A', borderColor: '#fff', _hogMeta: datasetMeta },
                    },
                ],
            })
            expect(buildTooltipContext(withDatasetMeta, chartBounds, [])!.points[0].meta).toBe(datasetMeta)

            const withoutDatasetMeta = makeTooltipModel({
                dataPoints: [{ datasetIndex: 0, dataIndex: 0, raw: 5, dataset: { label: 'A', borderColor: '#fff' } }],
            })
            const seriesData: Series[] = [{ label: 'A', data: [], meta: seriesMeta }]
            expect(buildTooltipContext(withoutDatasetMeta, chartBounds, seriesData)!.points[0].meta).toBe(seriesMeta)
        })
    })
})
