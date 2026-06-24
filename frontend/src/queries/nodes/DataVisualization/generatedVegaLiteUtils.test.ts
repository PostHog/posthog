import {
    buildSQLVisualizationGenerationRequest,
    validateVegaLiteSpec,
    VegaLiteValidationError,
} from './generatedVegaLiteUtils'

describe('generatedVegaLiteUtils', () => {
    describe('buildSQLVisualizationGenerationRequest', () => {
        it('maps columns, aliases duplicate names, truncates values, and caps samples', () => {
            const response = {
                columns: ['count', 'count', 'toStartOfDay(timestamp)', 'payload'],
                types: [
                    ['count', 'Int64'],
                    ['count', 'Float64'],
                    ['toStartOfDay(timestamp)', 'DateTime'],
                    ['payload', 'String'],
                ],
                results: Array.from({ length: 25 }, (_, index) => [
                    index,
                    index + 0.5,
                    `2025-01-${String((index % 9) + 1).padStart(2, '0')} 00:00:00`,
                    `${'x'.repeat(250)}-${index}`,
                ]),
            }

            const request = buildSQLVisualizationGenerationRequest('select * from events', 'make a chart', response, {
                view: { width: 900, height: 500 },
            })

            expect(request.fields.map((field) => field.field)).toEqual([
                'count',
                'field_1',
                'toStartOfDay_timestamp',
                'payload',
            ])
            expect(request.rowCount).toBe(25)
            expect(request.sampleRows).toHaveLength(20)
            expect(request.sampleRows[0].payload).toEqual(`${'x'.repeat(200)}...`)
            expect(request.columns[0]).toEqual(
                expect.objectContaining({
                    name: 'count',
                    type: 'Int64',
                    semanticType: 'quantitative',
                    sampleValues: expect.arrayContaining([0, 1, 2]),
                })
            )
            expect(request.columns[0].sampleValues).toHaveLength(10)
            expect(request.columns[2].semanticType).toBe('temporal')
            expect(request.view).toEqual({ width: 900, height: 500 })
        })
    })

    describe('validateVegaLiteSpec', () => {
        const fields = [
            { field: 'day', sourceColumn: 'day', label: 'day', type: 'DateTime', semanticType: 'temporal' as const },
            {
                field: 'count',
                sourceColumn: 'count',
                label: 'count',
                type: 'Int64',
                semanticType: 'quantitative' as const,
            },
            { field: 'name', sourceColumn: 'name', label: 'name', type: 'String', semanticType: 'nominal' as const },
        ]

        it('normalizes a Vega-Lite spec with the PostHog data source', () => {
            expect(
                validateVegaLiteSpec(
                    {
                        mark: 'line',
                        encoding: {
                            x: { field: 'day', type: 'temporal' },
                            y: { field: 'count', type: 'quantitative' },
                        },
                    },
                    fields
                ).spec
            ).toEqual(
                expect.objectContaining({
                    $schema: 'https://vega.github.io/schema/vega-lite/v6.json',
                    data: { name: 'posthog_results' },
                    mark: 'line',
                })
            )
        })

        it('accepts full Vega-Lite transforms, params, datasets, inline values, and URLs', () => {
            const result = validateVegaLiteSpec(
                {
                    $schema: 'https://vega.github.io/schema/vega-lite/v6.json',
                    datasets: {
                        thresholds: [{ level: 10 }],
                    },
                    data: { url: 'https://example.com/data.json', format: { type: 'json' } },
                    params: [{ name: 'hover', select: { type: 'point', on: 'pointerover' } }],
                    transform: [
                        { calculate: 'datum.count * 2', as: 'double_count' },
                        { filter: 'datum.double_count > 0' },
                        { lookup: 'name', from: { data: { name: 'thresholds' }, key: 'name', fields: ['level'] } },
                    ],
                    mark: { type: 'bar', href: 'https://example.com' },
                    encoding: {
                        x: { field: 'name', type: 'nominal' },
                        y: { field: 'double_count', type: 'quantitative' },
                    },
                },
                fields
            )

            expect(result.spec).toEqual(
                expect.objectContaining({
                    data: { url: 'https://example.com/data.json', format: { type: 'json' } },
                    params: [{ name: 'hover', select: { type: 'point', on: 'pointerover' } }],
                    transform: expect.arrayContaining([{ calculate: 'datum.count * 2', as: 'double_count' }]),
                })
            )
            expect(result.warnings).toEqual([])
        })

        it('accepts raw Vega specs and adds a PostHog dataset when data is omitted', () => {
            const result = validateVegaLiteSpec(
                {
                    $schema: 'https://vega.github.io/schema/vega/v6.json',
                    width: 400,
                    height: 200,
                    signals: [{ name: 'barStep', value: 20 }],
                    scales: [
                        {
                            name: 'xscale',
                            type: 'band',
                            domain: { data: 'posthog_results', field: 'name' },
                            range: 'width',
                        },
                        {
                            name: 'yscale',
                            type: 'linear',
                            domain: { data: 'posthog_results', field: 'count' },
                            range: 'height',
                        },
                    ],
                    marks: [
                        {
                            type: 'rect',
                            from: { data: 'posthog_results' },
                            encode: {
                                enter: {
                                    x: { scale: 'xscale', field: 'name' },
                                    y: { scale: 'yscale', field: 'count' },
                                    y2: { scale: 'yscale', value: 0 },
                                },
                            },
                        },
                    ],
                },
                fields
            )

            expect(result.spec.data).toEqual([{ name: 'posthog_results' }])
            expect(result.spec.marks).toEqual(expect.any(Array))
        })

        it('infers raw Vega when Vega-only top-level keys are present', () => {
            const result = validateVegaLiteSpec(
                {
                    width: 400,
                    height: 200,
                    data: [{ name: 'external', url: 'https://example.com/data.csv', format: { type: 'csv' } }],
                    marks: [
                        { type: 'text', from: { data: 'external' }, encode: { enter: { text: { field: 'name' } } } },
                    ],
                },
                fields
            )

            expect(result.spec.$schema).toBe('https://vega.github.io/schema/vega/v6.json')
            expect(result.spec.data).toEqual([
                { name: 'external', url: 'https://example.com/data.csv', format: { type: 'csv' } },
            ])
        })

        it('rejects unsupported schemas', () => {
            expect(() =>
                validateVegaLiteSpec(
                    {
                        $schema: 'https://example.com/not-vega.json',
                        data: { name: 'posthog_results' },
                        mark: 'bar',
                    },
                    fields
                )
            ).toThrow(VegaLiteValidationError)
        })

        it('rejects oversized specs', () => {
            expect(() =>
                validateVegaLiteSpec(
                    {
                        data: { name: 'posthog_results' },
                        mark: 'bar',
                        description: 'x'.repeat(250001),
                    },
                    fields
                )
            ).toThrow(VegaLiteValidationError)
        })

        it('rejects non-object specs', () => {
            expect(() => validateVegaLiteSpec([], fields)).toThrow(VegaLiteValidationError)
        })
    })
})
