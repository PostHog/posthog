import { buildKeaFormDefaultFromSourceDetails, getErrorsForFields } from './sourceWizardLogic'

describe('sourceWizardLogic', () => {
    describe('buildKeaFormDefaultFromSourceDetails', () => {
        it('returns the default for an empty source', async () => {
            const res = buildKeaFormDefaultFromSourceDetails({})

            expect(res).toEqual({ prefix: '', payload: {} })
        })

        it('returns defaults for text fields', async () => {
            const sourceWizardLogic = await import('./sourceWizardLogic')
            const res = sourceWizardLogic.buildKeaFormDefaultFromSourceDetails({
                Test: {
                    name: 'Stripe',
                    iconPath: '',
                    caption: null,
                    fields: [
                        {
                            name: 'test_field',
                            label: 'Test',
                            type: 'text',
                            required: true,
                            placeholder: 'Enter something',
                        },
                    ],
                },
            })

            expect(res).toEqual({ prefix: '', payload: { test_field: '' } })
        })

        it('returns defaults for pure select field', async () => {
            const sourceWizardLogic = await import('./sourceWizardLogic')
            const res = sourceWizardLogic.buildKeaFormDefaultFromSourceDetails({
                Test: {
                    name: 'Stripe',
                    iconPath: '',
                    caption: null,
                    fields: [
                        {
                            name: 'test_field',
                            label: 'Test',
                            type: 'select',
                            required: true,
                            options: [{ value: 'value1', label: 'label' }],
                            defaultValue: 'value1',
                        },
                    ],
                },
            })

            expect(res).toEqual({ prefix: '', payload: { test_field: 'value1' } })
        })

        it('returns defaults for select field with fields', async () => {
            const sourceWizardLogic = await import('./sourceWizardLogic')
            const res = sourceWizardLogic.buildKeaFormDefaultFromSourceDetails({
                Test: {
                    name: 'Stripe',
                    iconPath: '',
                    caption: null,
                    fields: [
                        {
                            name: 'test_field',
                            label: 'Test',
                            type: 'select',
                            required: true,
                            options: [
                                {
                                    value: 'value1',
                                    label: 'label',
                                    fields: [
                                        {
                                            name: 'option_field',
                                            label: 'Test',
                                            type: 'text',
                                            required: true,
                                            placeholder: 'Enter something',
                                        },
                                    ],
                                },
                            ],
                            defaultValue: 'value1',
                        },
                    ],
                },
            })

            expect(res).toEqual({ prefix: '', payload: { test_field: { selection: 'value1', option_field: '' } } })
        })

        it('returns defaults for switch group field - default disabled', async () => {
            const sourceWizardLogic = await import('./sourceWizardLogic')
            const res = sourceWizardLogic.buildKeaFormDefaultFromSourceDetails({
                Test: {
                    name: 'Stripe',
                    iconPath: '',
                    caption: null,
                    fields: [
                        {
                            name: 'test_field',
                            label: 'Test',
                            type: 'switch-group',
                            default: false,
                            fields: [
                                {
                                    name: 'option_field',
                                    label: 'Test',
                                    type: 'text',
                                    required: true,
                                    placeholder: 'Enter something',
                                },
                            ],
                        },
                    ],
                },
            })

            expect(res).toEqual({ prefix: '', payload: { test_field: { enabled: false, option_field: '' } } })
        })

        it('returns defaults for switch group field - default enabled', async () => {
            const sourceWizardLogic = await import('./sourceWizardLogic')
            const res = sourceWizardLogic.buildKeaFormDefaultFromSourceDetails({
                Test: {
                    name: 'Stripe',
                    iconPath: '',
                    caption: null,
                    fields: [
                        {
                            name: 'test_field',
                            label: 'Test',
                            type: 'switch-group',
                            default: true,
                            fields: [
                                {
                                    name: 'option_field',
                                    label: 'Test',
                                    type: 'text',
                                    required: true,
                                    placeholder: 'Enter something',
                                },
                            ],
                        },
                    ],
                },
            })

            expect(res).toEqual({ prefix: '', payload: { test_field: { enabled: true, option_field: '' } } })
        })
    })

    describe('getErrorsForFields', () => {
        it('returns no errors for an empty payload', () => {
            const res = getErrorsForFields([], { prefix: '', payload: {} })
            expect(res).toEqual({ payload: {} })
        })

        it('returns errors for an invalid prefix', () => {
            const res = getErrorsForFields([], { prefix: '@@@', payload: {} })
            expect(res.prefix).toBeTruthy()
        })

        it('returns errors for an empty required text field', () => {
            const res = getErrorsForFields(
                [
                    {
                        name: 'test_field',
                        label: 'Test',
                        type: 'text',
                        required: true,
                        placeholder: 'Enter something',
                    },
                ],
                { prefix: '', payload: {} }
            )
            expect(res.payload.test_field).toBeTruthy()
        })

        it('returns no errors for an empty non-required text field', () => {
            const res = getErrorsForFields(
                [
                    {
                        name: 'test_field',
                        label: 'Test',
                        type: 'text',
                        required: false,
                        placeholder: 'Enter something',
                    },
                ],
                { prefix: '', payload: {} }
            )
            expect(res.payload).toEqual({})
        })

        it('returns errors for an empty required select field', () => {
            const res = getErrorsForFields(
                [
                    {
                        name: 'test_field',
                        label: 'Test',
                        type: 'select',
                        required: true,
                        options: [{ value: 'value', label: 'label' }],
                        defaultValue: 'value',
                    },
                ],
                { prefix: '', payload: {} }
            )
            expect(res.payload.test_field).toBeTruthy()
        })

        it('returns no errors for an empty non-required select field', () => {
            const res = getErrorsForFields(
                [
                    {
                        name: 'test_field',
                        label: 'Test',
                        type: 'select',
                        required: false,
                        options: [{ value: 'value', label: 'label' }],
                        defaultValue: 'value',
                    },
                ],
                { prefix: '', payload: {} }
            )
            expect(res.payload).toEqual({})
        })

        it('returns errors for empty children fields of select field', () => {
            const res = getErrorsForFields(
                [
                    {
                        name: 'test_field',
                        label: 'Test',
                        type: 'select',
                        required: true,
                        options: [
                            {
                                value: 'value',
                                label: 'label',
                                fields: [
                                    {
                                        name: 'option_field',
                                        label: 'Test',
                                        type: 'text',
                                        required: true,
                                        placeholder: 'Enter something',
                                    },
                                ],
                            },
                        ],
                        defaultValue: 'value',
                    },
                ],
                { prefix: '', payload: { test_field: { selection: 'value', option_field: '' } } }
            )
            expect(res.payload.test_field.option_field).toBeTruthy()
        })

        it('returns no errors for empty children fields of select field that arent selected', () => {
            const res = getErrorsForFields(
                [
                    {
                        name: 'test_field',
                        label: 'Test',
                        type: 'select',
                        required: true,
                        options: [
                            {
                                value: 'value',
                                label: 'label',
                                fields: [
                                    {
                                        name: 'option_field',
                                        label: 'Test',
                                        type: 'text',
                                        required: true,
                                        placeholder: 'Enter something',
                                    },
                                ],
                            },
                            {
                                value: 'other_value',
                                label: 'label',
                                fields: [
                                    {
                                        name: 'non_selected_value',
                                        label: 'Test',
                                        type: 'text',
                                        required: true,
                                        placeholder: 'Enter something',
                                    },
                                ],
                            },
                        ],
                        defaultValue: 'value',
                    },
                ],
                {
                    prefix: '',
                    payload: { test_field: { selection: 'value', option_field: 'hello', non_selected_value: '' } },
                }
            )
            expect(res.payload.test_field.option_field).toBeUndefined()
            expect(res.payload.test_field.non_selected_value).toBeUndefined()
        })

        it('returns no errors for an empty non-required text field within a switch group field', () => {
            const res = getErrorsForFields(
                [
                    {
                        name: 'test_field',
                        label: 'Test',
                        type: 'switch-group',
                        default: false,
                        fields: [
                            {
                                name: 'option_field',
                                label: 'Test',
                                type: 'text',
                                required: false,
                                placeholder: 'Enter something',
                            },
                        ],
                    },
                ],
                { prefix: '', payload: { test_field: { enabled: true, option_field: '' } } }
            )
            expect(res.payload.test_field).toEqual({})
        })

        it('returns no errors for an empty required text field within a disabled switch group field', () => {
            const res = getErrorsForFields(
                [
                    {
                        name: 'test_field',
                        label: 'Test',
                        type: 'switch-group',
                        default: false,
                        fields: [
                            {
                                name: 'option_field',
                                label: 'Test',
                                type: 'text',
                                required: true,
                                placeholder: 'Enter something',
                            },
                        ],
                    },
                ],
                { prefix: '', payload: { test_field: { enabled: false, option_field: '' } } }
            )
            expect(res.payload).toEqual({})
        })

        it('returns no errors for a filled required text field within a switch group field', () => {
            const res = getErrorsForFields(
                [
                    {
                        name: 'test_field',
                        label: 'Test',
                        type: 'switch-group',
                        default: false,
                        fields: [
                            {
                                name: 'option_field',
                                label: 'Test',
                                type: 'text',
                                required: true,
                                placeholder: 'Enter something',
                            },
                        ],
                    },
                ],
                { prefix: '', payload: { test_field: { enabled: true, option_field: 'some_value' } } }
            )
            expect(res.payload.test_field).toEqual({})
        })

        it('returns errors for an empty required text field within a switch group field', () => {
            const res = getErrorsForFields(
                [
                    {
                        name: 'test_field',
                        label: 'Test',
                        type: 'switch-group',
                        default: false,
                        fields: [
                            {
                                name: 'option_field',
                                label: 'Test',
                                type: 'text',
                                required: true,
                                placeholder: 'Enter something',
                            },
                        ],
                    },
                ],
                { prefix: '', payload: { test_field: { enabled: true, option_field: '' } } }
            )
            expect(res.payload.test_field.option_field).toBeTruthy()
        })
    })
})
