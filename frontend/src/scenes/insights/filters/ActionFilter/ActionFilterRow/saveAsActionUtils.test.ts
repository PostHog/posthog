import { NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import {
    generateActionNameFromSeriesNode,
    isAutocaptureSeriesWithElements,
    operatorToStringMatching,
    seriesNodeToActionStep,
} from './saveAsActionUtils'
import { makeSeriesNode } from './testHelpers'

describe('saveAsActionUtils', () => {
    describe('isAutocaptureSeriesWithElements', () => {
        it.each([
            [
                'autocapture with $el_text property',
                makeSeriesNode({
                    properties: [
                        {
                            key: '$el_text',
                            value: 'Submit',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                    ],
                }),
                true,
            ],
            [
                'autocapture with element text property',
                makeSeriesNode({
                    properties: [
                        {
                            key: 'text',
                            value: 'Submit',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Element,
                        },
                    ],
                }),
                true,
            ],
            [
                'autocapture with selector property',
                makeSeriesNode({
                    properties: [
                        {
                            key: 'selector',
                            value: '.btn',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Element,
                        },
                    ],
                }),
                true,
            ],
            [
                'autocapture with href property',
                makeSeriesNode({
                    properties: [
                        {
                            key: 'href',
                            value: '/foo',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Element,
                        },
                    ],
                }),
                true,
            ],
            [
                'autocapture with no element properties',
                makeSeriesNode({
                    properties: [
                        {
                            key: '$browser',
                            value: 'Chrome',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                    ],
                }),
                false,
            ],
            ['autocapture with empty properties', makeSeriesNode({ properties: [] }), false],
            [
                'autocapture with only negated element operators',
                makeSeriesNode({
                    properties: [
                        {
                            key: '$el_text',
                            value: 'Submit',
                            operator: PropertyOperator.NotIContains,
                            type: PropertyFilterType.Event,
                        },
                    ],
                }),
                false,
            ],
            [
                'selector with regex operator (no matching field to store it)',
                makeSeriesNode({
                    properties: [
                        {
                            key: 'selector',
                            value: '.btn.*',
                            operator: PropertyOperator.Regex,
                            type: PropertyFilterType.Element,
                        },
                    ],
                }),
                false,
            ],
            [
                'selector with icontains operator (no matching field to store it)',
                makeSeriesNode({
                    properties: [
                        {
                            key: 'selector',
                            value: 'btn',
                            operator: PropertyOperator.IContains,
                            type: PropertyFilterType.Element,
                        },
                    ],
                }),
                false,
            ],
            [
                'non-autocapture event with element-like properties',
                makeSeriesNode({
                    event: '$pageview',
                    name: '$pageview',
                    properties: [
                        {
                            key: '$el_text',
                            value: 'Submit',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                    ],
                }),
                false,
            ],
            [
                'action type filter',
                makeSeriesNode({
                    kind: NodeKind.ActionsNode,
                    id: 123,
                    name: 'My Action',
                    properties: [
                        {
                            key: '$el_text',
                            value: 'Submit',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                    ],
                }),
                false,
            ],
        ])('%s → %s', (_description, filter, expected) => {
            expect(isAutocaptureSeriesWithElements(filter)).toBe(expected)
        })
    })

    describe('operatorToStringMatching', () => {
        it.each([
            [PropertyOperator.Exact, 'exact'],
            [PropertyOperator.IContains, 'contains'],
            [PropertyOperator.Regex, 'regex'],
            [PropertyOperator.NotIContains, null],
            [PropertyOperator.NotRegex, null],
            [PropertyOperator.GreaterThan, null],
            [PropertyOperator.IsSet, null],
            [PropertyOperator.IsNot, null],
            [undefined, null],
        ] as const)('maps %s → %s', (operator, expected) => {
            expect(operatorToStringMatching(operator)).toBe(expected)
        })
    })

    describe('seriesNodeToActionStep', () => {
        it('converts $el_text property to text field', () => {
            const filter = makeSeriesNode({
                properties: [
                    {
                        key: '$el_text',
                        value: 'Submit',
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    },
                ],
            })
            expect(seriesNodeToActionStep(filter)).toEqual({
                event: '$autocapture',
                text: 'Submit',
                text_matching: 'exact',
            })
        })

        it('converts element text property to text field', () => {
            const filter = makeSeriesNode({
                properties: [
                    {
                        key: 'text',
                        value: 'Click me',
                        operator: PropertyOperator.IContains,
                        type: PropertyFilterType.Element,
                    },
                ],
            })
            expect(seriesNodeToActionStep(filter)).toEqual({
                event: '$autocapture',
                text: 'Click me',
                text_matching: 'contains',
            })
        })

        it('converts selector property', () => {
            const filter = makeSeriesNode({
                properties: [
                    {
                        key: 'selector',
                        value: '.btn-primary',
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Element,
                    },
                ],
            })
            expect(seriesNodeToActionStep(filter)).toEqual({
                event: '$autocapture',
                selector: '.btn-primary',
            })
        })

        it('converts href property', () => {
            const filter = makeSeriesNode({
                properties: [
                    {
                        key: 'href',
                        value: '/signup',
                        operator: PropertyOperator.Regex,
                        type: PropertyFilterType.Element,
                    },
                ],
            })
            expect(seriesNodeToActionStep(filter)).toEqual({
                event: '$autocapture',
                href: '/signup',
                href_matching: 'regex',
            })
        })

        it('combines multiple element properties', () => {
            const filter = makeSeriesNode({
                properties: [
                    {
                        key: '$el_text',
                        value: 'Submit',
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    },
                    {
                        key: 'selector',
                        value: '.btn',
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Element,
                    },
                ],
            })
            expect(seriesNodeToActionStep(filter)).toEqual({
                event: '$autocapture',
                text: 'Submit',
                text_matching: 'exact',
                selector: '.btn',
            })
        })

        it('preserves non-element properties in the properties array', () => {
            const browserProp: AnyPropertyFilter = {
                key: '$browser',
                value: 'Chrome',
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Event,
            }
            const filter = makeSeriesNode({
                properties: [
                    {
                        key: '$el_text',
                        value: 'Submit',
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    },
                    browserProp,
                ],
            })
            const result = seriesNodeToActionStep(filter)
            expect(result.text).toBe('Submit')
            expect(result.properties).toEqual([browserProp])
        })

        it('preserves negated operators in remainingProperties instead of converting', () => {
            const negatedProp: AnyPropertyFilter = {
                key: '$el_text',
                value: 'Submit',
                operator: PropertyOperator.NotIContains,
                type: PropertyFilterType.Event,
            }
            const filter = makeSeriesNode({
                properties: [negatedProp],
            })
            const result = seriesNodeToActionStep(filter)
            expect(result.text).toBeUndefined()
            expect(result.properties).toEqual([negatedProp])
        })

        it('preserves multi-value array properties in remainingProperties', () => {
            const arrayProp: AnyPropertyFilter = {
                key: '$el_text',
                value: ['Submit', 'Cancel'],
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Event,
            }
            const filter = makeSeriesNode({
                properties: [arrayProp],
            })
            const result = seriesNodeToActionStep(filter)
            expect(result.text).toBeUndefined()
            expect(result.properties).toEqual([arrayProp])
        })

        it('only takes the first of duplicate element keys', () => {
            const secondTextProp: AnyPropertyFilter = {
                key: '$el_text',
                value: 'Cancel',
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Event,
            }
            const filter = makeSeriesNode({
                properties: [
                    {
                        key: '$el_text',
                        value: 'Submit',
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    },
                    secondTextProp,
                ],
            })
            const result = seriesNodeToActionStep(filter)
            expect(result.text).toBe('Submit')
            expect(result.properties).toEqual([secondTextProp])
        })
    })

    describe('generateActionNameFromSeriesNode', () => {
        it.each([
            [
                'text property',
                makeSeriesNode({
                    properties: [
                        {
                            key: '$el_text',
                            value: 'Submit',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                    ],
                }),
                'Autocapture: "Submit"',
            ],
            [
                'selector property',
                makeSeriesNode({
                    properties: [
                        {
                            key: 'selector',
                            value: '.btn-primary',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Element,
                        },
                    ],
                }),
                'Autocapture: .btn-primary',
            ],
            [
                'href property',
                makeSeriesNode({
                    properties: [
                        {
                            key: 'href',
                            value: '/signup',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Element,
                        },
                    ],
                }),
                'Autocapture: link "/signup"',
            ],
            [
                'text takes priority over selector',
                makeSeriesNode({
                    properties: [
                        {
                            key: '$el_text',
                            value: 'Submit',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                        {
                            key: 'selector',
                            value: '.btn',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Element,
                        },
                    ],
                }),
                'Autocapture: "Submit"',
            ],
            [
                'array value uses first element',
                makeSeriesNode({
                    properties: [
                        {
                            key: '$el_text',
                            value: ['Submit', 'Cancel'],
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                    ],
                }),
                'Autocapture: "Submit"',
            ],
            [
                'skips negated props and uses next valid prop for name',
                makeSeriesNode({
                    properties: [
                        {
                            key: '$el_text',
                            value: 'Submit',
                            operator: PropertyOperator.NotIContains,
                            type: PropertyFilterType.Event,
                        },
                        {
                            key: 'selector',
                            value: '.btn',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Element,
                        },
                    ],
                }),
                'Autocapture: .btn',
            ],
            ['empty properties', makeSeriesNode({ properties: [] }), 'Autocapture action'],
            [
                'properties with empty values',
                makeSeriesNode({
                    properties: [
                        {
                            key: '$el_text',
                            value: '',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                    ],
                }),
                'Autocapture action',
            ],
        ])('%s → %s', (_description, filter, expected) => {
            expect(generateActionNameFromSeriesNode(filter)).toBe(expected)
        })

        it('truncates long values', () => {
            const longText = 'a'.repeat(100)
            const filter = makeSeriesNode({
                properties: [
                    {
                        key: '$el_text',
                        value: longText,
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    },
                ],
            })
            const name = generateActionNameFromSeriesNode(filter)
            expect(name.length).toBeLessThan(70)
            expect(name).toContain('...')
        })
    })
})
