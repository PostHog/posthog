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

        const validBaseSpec = {
            data: { name: 'posthog_results' },
            mark: 'line',
            encoding: {
                x: { field: 'day', type: 'temporal' },
                y: { field: 'count', type: 'quantitative' },
            },
        }

        it.each([
            ['line', { ...validBaseSpec, mark: 'line' }],
            ['bar', { ...validBaseSpec, mark: 'bar' }],
            [
                'scatter',
                {
                    data: { name: 'posthog_results' },
                    mark: 'point',
                    encoding: {
                        x: { field: 'count', type: 'quantitative' },
                        y: { field: 'name', type: 'nominal' },
                    },
                },
            ],
        ])('accepts a simple %s spec', (_, spec) => {
            expect(validateVegaLiteSpec(spec, fields).spec).toEqual(
                expect.objectContaining({
                    $schema: 'https://vega.github.io/schema/vega-lite/v6.json',
                    data: { name: 'posthog_results' },
                })
            )
        })

        it('accepts pie and donut specs with safe arc mark properties', () => {
            const result = validateVegaLiteSpec(
                {
                    data: { name: 'posthog_results' },
                    mark: { type: 'arc', innerRadius: 60, outerRadius: 240, cornerRadius: 4, padAngle: 0.02 },
                    encoding: {
                        theta: { field: 'count', type: 'quantitative' },
                        color: { field: 'name', type: 'nominal', legend: { orient: 'right' } },
                        tooltip: [
                            { field: 'name', type: 'nominal' },
                            { field: 'count', type: 'quantitative' },
                        ],
                    },
                },
                fields
            )

            expect(result.spec.mark).toEqual(
                expect.objectContaining({ type: 'arc', innerRadius: 60, outerRadius: 130 })
            )
            expect(result.spec).toEqual(
                expect.objectContaining({
                    encoding: expect.objectContaining({
                        color: expect.objectContaining({
                            legend: expect.objectContaining({
                                orient: 'bottom',
                                direction: 'horizontal',
                                labelLimit: 180,
                            }),
                        }),
                    }),
                })
            )
            expect(result.spec.padding).toEqual({ top: 24, right: 32, bottom: 72, left: 32 })
            expect(result.warnings).toEqual([])
        })

        it('accepts rounded bar corner properties', () => {
            const result = validateVegaLiteSpec(
                {
                    data: { name: 'posthog_results' },
                    mark: { type: 'bar', cornerRadiusTopLeft: 4, cornerRadiusTopRight: 4 },
                    encoding: {
                        x: { field: 'name', type: 'nominal' },
                        y: { field: 'count', type: 'quantitative' },
                    },
                },
                fields
            )

            expect(result.spec.mark).toEqual(
                expect.objectContaining({ cornerRadiusTopLeft: 4, cornerRadiusTopRight: 4 })
            )
            expect(result.spec.padding).toEqual({ top: 24, right: 32, bottom: 56, left: 64 })
        })

        it('accepts common axis and legend typography config', () => {
            const result = validateVegaLiteSpec(
                {
                    data: { name: 'posthog_results' },
                    mark: 'bar',
                    encoding: {
                        x: {
                            field: 'name',
                            type: 'nominal',
                            axis: { labelFontSize: 11, titleFontSize: 13, labelColor: '#666' },
                        },
                        y: { field: 'count', type: 'quantitative' },
                        color: {
                            field: 'name',
                            type: 'nominal',
                            legend: { labelFontSize: 11, titleFontSize: 13 },
                        },
                    },
                    config: {
                        axis: { labelFontSize: 12, titleFontSize: 14, gridDash: [2, 2] },
                        axisBottom: { labelAngle: -30, labelFontSize: 10 },
                        legend: { labelFontSize: 11, titleFontSize: 13 },
                        title: { subtitleFontSize: 12 },
                    },
                },
                fields
            )

            expect(result.spec.config).toEqual(
                expect.objectContaining({
                    axis: expect.objectContaining({ labelFontSize: 12, titleFontSize: 14 }),
                    axisBottom: expect.objectContaining({ labelFontSize: 10 }),
                    legend: expect.objectContaining({ labelFontSize: 11, titleFontSize: 13 }),
                    title: expect.objectContaining({ subtitleFontSize: 12 }),
                })
            )
            expect(result.warnings).toEqual([])
        })

        it('strips null config blocks before rendering', () => {
            const result = validateVegaLiteSpec(
                {
                    data: { name: 'posthog_results' },
                    mark: 'bar',
                    encoding: {
                        x: { field: 'name', type: 'nominal' },
                        y: { field: 'count', type: 'quantitative' },
                    },
                    config: {
                        axis: null,
                        legend: null,
                    },
                },
                fields
            )

            expect(result.spec.config).toEqual({})
            expect(result.warnings).toEqual([
                'Removed null config block "axis".',
                'Removed null config block "legend".',
            ])
        })

        it('strips unsupported decorative keys and returns warnings', () => {
            const result = validateVegaLiteSpec(
                {
                    data: { name: 'posthog_results' },
                    mark: { type: 'bar', madeUpSparkle: true },
                    encoding: {
                        x: { field: 'name', type: 'nominal', madeUpAxisThing: true },
                        y: { field: 'count', type: 'quantitative' },
                    },
                },
                fields
            )

            expect(result.spec.mark).toEqual({ type: 'bar' })
            expect(result.spec.encoding).toEqual({
                x: { field: 'name', type: 'nominal' },
                y: { field: 'count', type: 'quantitative' },
            })
            expect(result.warnings).toEqual([
                'Removed unsupported key "madeUpSparkle" at spec.mark.',
                'Removed unsupported key "madeUpAxisThing" at encoding.x.',
            ])
        })

        it.each([
            ['data.url', { ...validBaseSpec, data: { name: 'posthog_results', url: 'https://example.com/data.json' } }],
            ['transform', { ...validBaseSpec, transform: [{ calculate: 'datum.count * 2', as: 'double_count' }] }],
            ['unknown field', { ...validBaseSpec, encoding: { y: { field: 'missing', type: 'quantitative' } } }],
            ['external resource string', { ...validBaseSpec, title: 'https://example.com' }],
            ['inline values', { ...validBaseSpec, data: { name: 'posthog_results', values: [{ count: 1 }] } }],
        ])('rejects %s', (_, spec) => {
            expect(() => validateVegaLiteSpec(spec, fields)).toThrow(VegaLiteValidationError)
        })

        it('rejects oversized specs', () => {
            expect(() => validateVegaLiteSpec({ ...validBaseSpec, description: 'x'.repeat(25000) }, fields)).toThrow(
                VegaLiteValidationError
            )
        })
    })
})
