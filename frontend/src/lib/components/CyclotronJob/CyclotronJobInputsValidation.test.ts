import { CyclotronJobInputSchemaType } from '~/types'

import { CyclotronJobInputsValidation } from './CyclotronJobInputsValidation'

describe('CyclotronJobInputsValidation', () => {
    describe('validate', () => {
        it('should return valid result when no inputs are provided', () => {
            const result = CyclotronJobInputsValidation.validate({}, [])

            expect(result).toEqual({
                valid: true,
                errors: {},
            })
        })

        it('should return valid result when no schema is provided', () => {
            const inputs = { test: { value: 'hello' } }
            const result = CyclotronJobInputsValidation.validate(inputs, [])

            expect(result).toEqual({
                valid: true,
                errors: {},
            })
        })

        describe('required field validation', () => {
            it('should error when required field is missing', () => {
                const inputs = {}
                const schema: CyclotronJobInputSchemaType[] = [
                    { key: 'name', type: 'string', label: 'Name', required: true },
                ]

                const result = CyclotronJobInputsValidation.validate(inputs, schema)

                expect(result.valid).toBe(false)
                expect(result.errors.name).toBe('This field is required')
            })

            it('should error when required field is null', () => {
                const inputs = { name: { value: null } }
                const schema: CyclotronJobInputSchemaType[] = [
                    { key: 'name', type: 'string', label: 'Name', required: true },
                ]

                const result = CyclotronJobInputsValidation.validate(inputs, schema)

                expect(result.valid).toBe(false)
                expect(result.errors.name).toBe('This field is required')
            })

            it('should error when required field is empty string', () => {
                const inputs = { name: { value: '' } }
                const schema: CyclotronJobInputSchemaType[] = [
                    { key: 'name', type: 'string', label: 'Name', required: true },
                ]

                const result = CyclotronJobInputsValidation.validate(inputs, schema)

                expect(result.valid).toBe(false)
                expect(result.errors.name).toBe('This field is required')
            })

            it('should pass when required field has value', () => {
                const inputs = { name: { value: 'John' } }
                const schema: CyclotronJobInputSchemaType[] = [
                    { key: 'name', type: 'string', label: 'Name', required: true },
                ]

                const result = CyclotronJobInputsValidation.validate(inputs, schema)

                expect(result.valid).toBe(true)
                expect(result.errors).toEqual({})
            })
        })

        describe('type validation', () => {
            it('should validate string type', () => {
                const inputs = { name: { value: 123 } }
                const schema: CyclotronJobInputSchemaType[] = [{ key: 'name', type: 'string', label: 'Name' }]

                const result = CyclotronJobInputsValidation.validate(inputs, schema)

                expect(result.valid).toBe(false)
                expect(result.errors.name).toBe('Value must be a string')
            })

            it('should validate number type', () => {
                const inputs = { age: { value: '25' } }
                const schema: CyclotronJobInputSchemaType[] = [{ key: 'age', type: 'number', label: 'Age' }]

                const result = CyclotronJobInputsValidation.validate(inputs, schema)

                expect(result.valid).toBe(false)
                expect(result.errors.age).toBe('Value must be a number')
            })

            it('should validate boolean type', () => {
                const inputs = { active: { value: 'true' } }
                const schema: CyclotronJobInputSchemaType[] = [{ key: 'active', type: 'boolean', label: 'Active' }]

                const result = CyclotronJobInputsValidation.validate(inputs, schema)

                expect(result.valid).toBe(false)
                expect(result.errors.active).toBe('Value must be a boolean')
            })

            it('should validate dictionary type', () => {
                const inputs = { config: { value: 'not an object' } }
                const schema: CyclotronJobInputSchemaType[] = [{ key: 'config', type: 'dictionary', label: 'Config' }]

                const result = CyclotronJobInputsValidation.validate(inputs, schema)

                expect(result.valid).toBe(false)
                expect(result.errors.config).toBe('Value must be a dictionary')
            })

            it('should validate integration type', () => {
                const inputs = { integration: { value: '123' } }
                const schema: CyclotronJobInputSchemaType[] = [
                    { key: 'integration', type: 'integration', label: 'Integration' },
                ]

                const result = CyclotronJobInputsValidation.validate(inputs, schema)

                expect(result.valid).toBe(false)
                expect(result.errors.integration).toBe('Value must be an Integration ID')
            })
        })

        describe('JSON validation', () => {
            it('should error on invalid JSON', () => {
                const inputs = { config: { value: '{ invalid json' } }
                const schema: CyclotronJobInputSchemaType[] = [{ key: 'config', type: 'json', label: 'Config' }]

                const result = CyclotronJobInputsValidation.validate(inputs, schema)

                expect(result.valid).toBe(false)
                expect(result.errors.config).toBe('Invalid JSON')
            })

            it('should pass on valid JSON', () => {
                const inputs = { config: { value: '{"key": "value"}' } }
                const schema: CyclotronJobInputSchemaType[] = [{ key: 'config', type: 'json', label: 'Config' }]

                const result = CyclotronJobInputsValidation.validate(inputs, schema)

                expect(result.valid).toBe(true)
                expect(result.errors).toEqual({})
            })
        })

        describe('email template validation', () => {
            it('should error when required email fields are missing', () => {
                const inputs = {
                    email: {
                        value: {
                            html: '',
                            subject: '',
                            from: '',
                            to: '',
                        },
                    },
                }
                const schema: CyclotronJobInputSchemaType[] = [{ key: 'email', type: 'email', label: 'Email' }]

                const result = CyclotronJobInputsValidation.validate(inputs, schema)

                expect(result.valid).toBe(false)
                expect(result.errors.email).toBe(
                    'HTML is required, Subject is required, From is required, To is required'
                )
            })

            it('should pass when all required email fields are present', () => {
                const inputs = {
                    email: {
                        value: {
                            html: '<p>Hello</p>',
                            subject: 'Test Subject',
                            from: 'test@example.com',
                            to: 'user@example.com',
                        },
                    },
                }
                const schema: CyclotronJobInputSchemaType[] = [{ key: 'email', type: 'email', label: 'Email' }]

                const result = CyclotronJobInputsValidation.validate(inputs, schema)

                expect(result.valid).toBe(true)
                expect(result.errors).toEqual({})
            })
        })

        describe('templating validation', () => {
            it('should validate liquid templates and return error on parse failure', () => {
                const inputs = { template: { value: '{% invalid %}', templating: 'liquid' as const } }
                const schema: CyclotronJobInputSchemaType[] = [{ key: 'template', type: 'string', label: 'Template' }]

                const result = CyclotronJobInputsValidation.validate(inputs, schema)

                expect(result.valid).toBe(false)
                expect(result.errors).toEqual({
                    template: 'Liquid template error: tag "invalid" not found, line:1, col:1',
                })
            })

            it('should pass when liquid template is valid', () => {
                const inputs = { template: { value: '{{ valid }}', templating: 'liquid' as const } }
                const schema: CyclotronJobInputSchemaType[] = [{ key: 'template', type: 'string', label: 'Template' }]

                const result = CyclotronJobInputsValidation.validate(inputs, schema)

                expect(result.valid).toBe(true)
                expect(result.errors).toEqual({})
            })

            it('should not validate templating for non-liquid languages', () => {
                const inputs = { template: { value: '{{ invalid }}', templating: 'hog' as const } }
                const schema: CyclotronJobInputSchemaType[] = [{ key: 'template', type: 'string', label: 'Template' }]

                const result = CyclotronJobInputsValidation.validate(inputs, schema)

                expect(result.valid).toBe(true)
                expect(result.errors).toEqual({})
            })

            it('should validate templating in dictionary values', () => {
                const inputs = {
                    config: {
                        templating: 'liquid' as const,
                        value: {
                            key1: '{% invalid %}',
                            key2: 'valid string',
                            key3: 123,
                        },
                    },
                }
                const schema: CyclotronJobInputSchemaType[] = [{ key: 'config', type: 'dictionary', label: 'Config' }]

                const result = CyclotronJobInputsValidation.validate(inputs, schema)

                expect(result.valid).toBe(false)
                expect(result.errors).toEqual({
                    config: 'Liquid template error: tag "invalid" not found, line:1, col:1',
                })
            })
        })

        describe('secret handling', () => {
            it('should skip validation for secret inputs', () => {
                const inputs = { password: { value: '', secret: true } }
                const schema: CyclotronJobInputSchemaType[] = [
                    { key: 'password', type: 'string', label: 'Password', required: true },
                ]

                const result = CyclotronJobInputsValidation.validate(inputs, schema)

                expect(result.valid).toBe(true)
                expect(result.errors).toEqual({})
            })

            it('should validate non-secret inputs even when secret inputs exist', () => {
                const inputs = {
                    password: { value: '', secret: true },
                    username: { value: '' },
                }
                const schema: CyclotronJobInputSchemaType[] = [
                    { key: 'password', type: 'string', label: 'Password', required: true },
                    { key: 'username', type: 'string', label: 'Username', required: true },
                ]

                const result = CyclotronJobInputsValidation.validate(inputs, schema)

                expect(result.valid).toBe(false)
                expect(result.errors.username).toBe('This field is required')
                expect(result.errors.password).toBeUndefined()
            })
        })

        describe('complex validation scenarios', () => {
            it('should handle multiple validation errors', () => {
                const inputs = {
                    name: { value: '' },
                    age: { value: 'not a number' },
                    email: {
                        value: {
                            html: '',
                            subject: '',
                            from: '',
                            to: '',
                        },
                    },
                }
                const schema: CyclotronJobInputSchemaType[] = [
                    { key: 'name', type: 'string', label: 'Name', required: true },
                    { key: 'age', type: 'number', label: 'Age' },
                    { key: 'email', type: 'email', label: 'Email' },
                ]

                const result = CyclotronJobInputsValidation.validate(inputs, schema)

                expect(result.valid).toBe(false)
                expect(Object.keys(result.errors)).toHaveLength(3)
                expect(result.errors.name).toBe('This field is required')
                expect(result.errors.age).toBe('Value must be a number')
                expect(result.errors.email).toContain('HTML is required')
            })

            it('should handle mixed valid and invalid inputs', () => {
                const inputs = {
                    validString: { value: 'hello' },
                    invalidNumber: { value: 'not a number' },
                    validObject: { value: { key: 'value' } },
                }
                const schema: CyclotronJobInputSchemaType[] = [
                    { key: 'validString', type: 'string', label: 'Valid String' },
                    { key: 'invalidNumber', type: 'number', label: 'Invalid Number' },
                    { key: 'validObject', type: 'dictionary', label: 'Valid Object' },
                ]

                const result = CyclotronJobInputsValidation.validate(inputs, schema)

                expect(result.valid).toBe(false)
                expect(result.errors.invalidNumber).toBe('Value must be a number')
                expect(result.errors.validString).toBeUndefined()
                expect(result.errors.validObject).toBeUndefined()
            })
        })
    })
})
