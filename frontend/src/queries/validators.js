// AUTO-GENERATED FILE - DO NOT EDIT DIRECTLY
'use strict'
export const AnyPropertyFilter = validate11
const schema12 = {
    anyOf: [
        { $ref: '#/definitions/EventPropertyFilter' },
        { $ref: '#/definitions/PersonPropertyFilter' },
        { $ref: '#/definitions/ElementPropertyFilter' },
        { $ref: '#/definitions/EventMetadataPropertyFilter' },
        { $ref: '#/definitions/SessionPropertyFilter' },
        { $ref: '#/definitions/CohortPropertyFilter' },
        { $ref: '#/definitions/RecordingPropertyFilter' },
        { $ref: '#/definitions/LogEntryPropertyFilter' },
        { $ref: '#/definitions/GroupPropertyFilter' },
        { $ref: '#/definitions/FeaturePropertyFilter' },
        { $ref: '#/definitions/FlagPropertyFilter' },
        { $ref: '#/definitions/HogQLPropertyFilter' },
        { $ref: '#/definitions/EmptyPropertyFilter' },
        { $ref: '#/definitions/DataWarehousePropertyFilter' },
        { $ref: '#/definitions/DataWarehousePersonPropertyFilter' },
        { $ref: '#/definitions/ErrorTrackingIssueFilter' },
        { $ref: '#/definitions/LogPropertyFilter' },
        { $ref: '#/definitions/RevenueAnalyticsPropertyFilter' },
    ],
}
const schema37 = {
    additionalProperties: false,
    properties: {
        key: { description: 'The key should be the flag ID', type: 'string' },
        label: { type: 'string' },
        operator: {
            const: 'flag_evaluates_to',
            description: 'Only flag_evaluates_to operator is allowed for flag dependencies',
            type: 'string',
        },
        type: { const: 'flag', description: 'Feature flag dependency', type: 'string' },
        value: { description: 'The value can be true, false, or a variant name', type: ['boolean', 'string'] },
    },
    required: ['key', 'operator', 'type', 'value'],
    type: 'object',
}
const schema39 = { additionalProperties: false, type: 'object' }
const schema13 = {
    additionalProperties: false,
    description: 'Sync with plugin-server/src/types.ts',
    properties: {
        key: { type: 'string' },
        label: { type: 'string' },
        operator: { $ref: '#/definitions/PropertyOperator', default: 'exact' },
        type: { const: 'event', description: 'Event properties', type: 'string' },
        value: { $ref: '#/definitions/PropertyFilterValue' },
    },
    required: ['key', 'operator', 'type'],
    type: 'object',
}
const schema14 = {
    description: 'Sync with plugin-server/src/types.ts',
    enum: [
        'exact',
        'is_not',
        'icontains',
        'not_icontains',
        'regex',
        'not_regex',
        'gt',
        'gte',
        'lt',
        'lte',
        'is_set',
        'is_not_set',
        'is_date_exact',
        'is_date_before',
        'is_date_after',
        'between',
        'not_between',
        'min',
        'max',
        'in',
        'not_in',
        'is_cleaned_path_exact',
        'flag_evaluates_to',
    ],
    type: 'string',
}
const schema15 = {
    anyOf: [
        { $ref: '#/definitions/PropertyFilterBaseValue' },
        { items: { $ref: '#/definitions/PropertyFilterBaseValue' }, type: 'array' },
        { type: 'null' },
    ],
}
const schema16 = { type: ['string', 'number', 'boolean'] }
function validate13(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    const _errs0 = errors
    let valid0 = false
    const _errs1 = errors
    if (typeof data !== 'string' && !(typeof data == 'number' && isFinite(data)) && typeof data !== 'boolean') {
        const err0 = {
            instancePath,
            schemaPath: '#/definitions/PropertyFilterBaseValue/type',
            keyword: 'type',
            params: { type: schema16.type },
            message: 'must be string,number,boolean',
        }
        if (vErrors === null) {
            vErrors = [err0]
        } else {
            vErrors.push(err0)
        }
        errors++
    }
    var _valid0 = _errs1 === errors
    valid0 = valid0 || _valid0
    if (!valid0) {
        const _errs4 = errors
        if (errors === _errs4) {
            if (Array.isArray(data)) {
                var valid2 = true
                const len0 = data.length
                for (let i0 = 0; i0 < len0; i0++) {
                    let data0 = data[i0]
                    const _errs6 = errors
                    if (
                        typeof data0 !== 'string' &&
                        !(typeof data0 == 'number' && isFinite(data0)) &&
                        typeof data0 !== 'boolean'
                    ) {
                        const err1 = {
                            instancePath: instancePath + '/' + i0,
                            schemaPath: '#/definitions/PropertyFilterBaseValue/type',
                            keyword: 'type',
                            params: { type: schema16.type },
                            message: 'must be string,number,boolean',
                        }
                        if (vErrors === null) {
                            vErrors = [err1]
                        } else {
                            vErrors.push(err1)
                        }
                        errors++
                    }
                    var valid2 = _errs6 === errors
                    if (!valid2) {
                        break
                    }
                }
            } else {
                const err2 = {
                    instancePath,
                    schemaPath: '#/anyOf/1/type',
                    keyword: 'type',
                    params: { type: 'array' },
                    message: 'must be array',
                }
                if (vErrors === null) {
                    vErrors = [err2]
                } else {
                    vErrors.push(err2)
                }
                errors++
            }
        }
        var _valid0 = _errs4 === errors
        valid0 = valid0 || _valid0
        if (!valid0) {
            const _errs9 = errors
            if (data !== null) {
                const err3 = {
                    instancePath,
                    schemaPath: '#/anyOf/2/type',
                    keyword: 'type',
                    params: { type: 'null' },
                    message: 'must be null',
                }
                if (vErrors === null) {
                    vErrors = [err3]
                } else {
                    vErrors.push(err3)
                }
                errors++
            }
            var _valid0 = _errs9 === errors
            valid0 = valid0 || _valid0
        }
    }
    if (!valid0) {
        const err4 = {
            instancePath,
            schemaPath: '#/anyOf',
            keyword: 'anyOf',
            params: {},
            message: 'must match a schema in anyOf',
        }
        if (vErrors === null) {
            vErrors = [err4]
        } else {
            vErrors.push(err4)
        }
        errors++
        validate13.errors = vErrors
        return false
    } else {
        errors = _errs0
        if (vErrors !== null) {
            if (_errs0) {
                vErrors.length = _errs0
            } else {
                vErrors = null
            }
        }
    }
    validate13.errors = vErrors
    return errors === 0
}
function validate12(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if (
                (data.key === undefined && (missing0 = 'key')) ||
                (data.operator === undefined && (missing0 = 'operator')) ||
                (data.type === undefined && (missing0 = 'type'))
            ) {
                validate12.errors = [
                    {
                        instancePath,
                        schemaPath: '#/required',
                        keyword: 'required',
                        params: { missingProperty: missing0 },
                        message: "must have required property '" + missing0 + "'",
                    },
                ]
                return false
            } else {
                const _errs1 = errors
                for (const key0 in data) {
                    if (
                        !(
                            key0 === 'key' ||
                            key0 === 'label' ||
                            key0 === 'operator' ||
                            key0 === 'type' ||
                            key0 === 'value'
                        )
                    ) {
                        validate12.errors = [
                            {
                                instancePath,
                                schemaPath: '#/additionalProperties',
                                keyword: 'additionalProperties',
                                params: { additionalProperty: key0 },
                                message: 'must NOT have additional properties',
                            },
                        ]
                        return false
                        break
                    }
                }
                if (_errs1 === errors) {
                    if (data.key !== undefined) {
                        const _errs2 = errors
                        if (typeof data.key !== 'string') {
                            validate12.errors = [
                                {
                                    instancePath: instancePath + '/key',
                                    schemaPath: '#/properties/key/type',
                                    keyword: 'type',
                                    params: { type: 'string' },
                                    message: 'must be string',
                                },
                            ]
                            return false
                        }
                        var valid0 = _errs2 === errors
                    } else {
                        var valid0 = true
                    }
                    if (valid0) {
                        if (data.label !== undefined) {
                            const _errs4 = errors
                            if (typeof data.label !== 'string') {
                                validate12.errors = [
                                    {
                                        instancePath: instancePath + '/label',
                                        schemaPath: '#/properties/label/type',
                                        keyword: 'type',
                                        params: { type: 'string' },
                                        message: 'must be string',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs4 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.operator !== undefined) {
                                let data2 = data.operator
                                const _errs6 = errors
                                if (typeof data2 !== 'string') {
                                    validate12.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/type',
                                            keyword: 'type',
                                            params: { type: 'string' },
                                            message: 'must be string',
                                        },
                                    ]
                                    return false
                                }
                                if (
                                    !(
                                        data2 === 'exact' ||
                                        data2 === 'is_not' ||
                                        data2 === 'icontains' ||
                                        data2 === 'not_icontains' ||
                                        data2 === 'regex' ||
                                        data2 === 'not_regex' ||
                                        data2 === 'gt' ||
                                        data2 === 'gte' ||
                                        data2 === 'lt' ||
                                        data2 === 'lte' ||
                                        data2 === 'is_set' ||
                                        data2 === 'is_not_set' ||
                                        data2 === 'is_date_exact' ||
                                        data2 === 'is_date_before' ||
                                        data2 === 'is_date_after' ||
                                        data2 === 'between' ||
                                        data2 === 'not_between' ||
                                        data2 === 'min' ||
                                        data2 === 'max' ||
                                        data2 === 'in' ||
                                        data2 === 'not_in' ||
                                        data2 === 'is_cleaned_path_exact' ||
                                        data2 === 'flag_evaluates_to'
                                    )
                                ) {
                                    validate12.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/enum',
                                            keyword: 'enum',
                                            params: { allowedValues: schema14.enum },
                                            message: 'must be equal to one of the allowed values',
                                        },
                                    ]
                                    return false
                                }
                                var valid0 = _errs6 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.type !== undefined) {
                                    let data3 = data.type
                                    const _errs9 = errors
                                    if (typeof data3 !== 'string') {
                                        validate12.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/type',
                                                keyword: 'type',
                                                params: { type: 'string' },
                                                message: 'must be string',
                                            },
                                        ]
                                        return false
                                    }
                                    if ('event' !== data3) {
                                        validate12.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/const',
                                                keyword: 'const',
                                                params: { allowedValue: 'event' },
                                                message: 'must be equal to constant',
                                            },
                                        ]
                                        return false
                                    }
                                    var valid0 = _errs9 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.value !== undefined) {
                                        const _errs11 = errors
                                        if (
                                            !validate13(data.value, {
                                                instancePath: instancePath + '/value',
                                                parentData: data,
                                                parentDataProperty: 'value',
                                                rootData,
                                            })
                                        ) {
                                            vErrors =
                                                vErrors === null ? validate13.errors : vErrors.concat(validate13.errors)
                                            errors = vErrors.length
                                        }
                                        var valid0 = _errs11 === errors
                                    } else {
                                        var valid0 = true
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } else {
            validate12.errors = [
                {
                    instancePath,
                    schemaPath: '#/type',
                    keyword: 'type',
                    params: { type: 'object' },
                    message: 'must be object',
                },
            ]
            return false
        }
    }
    validate12.errors = vErrors
    return errors === 0
}
const schema18 = {
    additionalProperties: false,
    description: 'Sync with plugin-server/src/types.ts',
    properties: {
        key: { type: 'string' },
        label: { type: 'string' },
        operator: { $ref: '#/definitions/PropertyOperator' },
        type: { const: 'person', description: 'Person properties', type: 'string' },
        value: { $ref: '#/definitions/PropertyFilterValue' },
    },
    required: ['key', 'operator', 'type'],
    type: 'object',
}
function validate16(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if (
                (data.key === undefined && (missing0 = 'key')) ||
                (data.operator === undefined && (missing0 = 'operator')) ||
                (data.type === undefined && (missing0 = 'type'))
            ) {
                validate16.errors = [
                    {
                        instancePath,
                        schemaPath: '#/required',
                        keyword: 'required',
                        params: { missingProperty: missing0 },
                        message: "must have required property '" + missing0 + "'",
                    },
                ]
                return false
            } else {
                const _errs1 = errors
                for (const key0 in data) {
                    if (
                        !(
                            key0 === 'key' ||
                            key0 === 'label' ||
                            key0 === 'operator' ||
                            key0 === 'type' ||
                            key0 === 'value'
                        )
                    ) {
                        validate16.errors = [
                            {
                                instancePath,
                                schemaPath: '#/additionalProperties',
                                keyword: 'additionalProperties',
                                params: { additionalProperty: key0 },
                                message: 'must NOT have additional properties',
                            },
                        ]
                        return false
                        break
                    }
                }
                if (_errs1 === errors) {
                    if (data.key !== undefined) {
                        const _errs2 = errors
                        if (typeof data.key !== 'string') {
                            validate16.errors = [
                                {
                                    instancePath: instancePath + '/key',
                                    schemaPath: '#/properties/key/type',
                                    keyword: 'type',
                                    params: { type: 'string' },
                                    message: 'must be string',
                                },
                            ]
                            return false
                        }
                        var valid0 = _errs2 === errors
                    } else {
                        var valid0 = true
                    }
                    if (valid0) {
                        if (data.label !== undefined) {
                            const _errs4 = errors
                            if (typeof data.label !== 'string') {
                                validate16.errors = [
                                    {
                                        instancePath: instancePath + '/label',
                                        schemaPath: '#/properties/label/type',
                                        keyword: 'type',
                                        params: { type: 'string' },
                                        message: 'must be string',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs4 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.operator !== undefined) {
                                let data2 = data.operator
                                const _errs6 = errors
                                if (typeof data2 !== 'string') {
                                    validate16.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/type',
                                            keyword: 'type',
                                            params: { type: 'string' },
                                            message: 'must be string',
                                        },
                                    ]
                                    return false
                                }
                                if (
                                    !(
                                        data2 === 'exact' ||
                                        data2 === 'is_not' ||
                                        data2 === 'icontains' ||
                                        data2 === 'not_icontains' ||
                                        data2 === 'regex' ||
                                        data2 === 'not_regex' ||
                                        data2 === 'gt' ||
                                        data2 === 'gte' ||
                                        data2 === 'lt' ||
                                        data2 === 'lte' ||
                                        data2 === 'is_set' ||
                                        data2 === 'is_not_set' ||
                                        data2 === 'is_date_exact' ||
                                        data2 === 'is_date_before' ||
                                        data2 === 'is_date_after' ||
                                        data2 === 'between' ||
                                        data2 === 'not_between' ||
                                        data2 === 'min' ||
                                        data2 === 'max' ||
                                        data2 === 'in' ||
                                        data2 === 'not_in' ||
                                        data2 === 'is_cleaned_path_exact' ||
                                        data2 === 'flag_evaluates_to'
                                    )
                                ) {
                                    validate16.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/enum',
                                            keyword: 'enum',
                                            params: { allowedValues: schema14.enum },
                                            message: 'must be equal to one of the allowed values',
                                        },
                                    ]
                                    return false
                                }
                                var valid0 = _errs6 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.type !== undefined) {
                                    let data3 = data.type
                                    const _errs9 = errors
                                    if (typeof data3 !== 'string') {
                                        validate16.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/type',
                                                keyword: 'type',
                                                params: { type: 'string' },
                                                message: 'must be string',
                                            },
                                        ]
                                        return false
                                    }
                                    if ('person' !== data3) {
                                        validate16.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/const',
                                                keyword: 'const',
                                                params: { allowedValue: 'person' },
                                                message: 'must be equal to constant',
                                            },
                                        ]
                                        return false
                                    }
                                    var valid0 = _errs9 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.value !== undefined) {
                                        const _errs11 = errors
                                        if (
                                            !validate13(data.value, {
                                                instancePath: instancePath + '/value',
                                                parentData: data,
                                                parentDataProperty: 'value',
                                                rootData,
                                            })
                                        ) {
                                            vErrors =
                                                vErrors === null ? validate13.errors : vErrors.concat(validate13.errors)
                                            errors = vErrors.length
                                        }
                                        var valid0 = _errs11 === errors
                                    } else {
                                        var valid0 = true
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } else {
            validate16.errors = [
                {
                    instancePath,
                    schemaPath: '#/type',
                    keyword: 'type',
                    params: { type: 'object' },
                    message: 'must be object',
                },
            ]
            return false
        }
    }
    validate16.errors = vErrors
    return errors === 0
}
const schema20 = {
    additionalProperties: false,
    description: 'Sync with plugin-server/src/types.ts',
    properties: {
        key: { enum: ['tag_name', 'text', 'href', 'selector'], type: 'string' },
        label: { type: 'string' },
        operator: { $ref: '#/definitions/PropertyOperator' },
        type: { const: 'element', type: 'string' },
        value: { $ref: '#/definitions/PropertyFilterValue' },
    },
    required: ['key', 'operator', 'type'],
    type: 'object',
}
function validate19(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if (
                (data.key === undefined && (missing0 = 'key')) ||
                (data.operator === undefined && (missing0 = 'operator')) ||
                (data.type === undefined && (missing0 = 'type'))
            ) {
                validate19.errors = [
                    {
                        instancePath,
                        schemaPath: '#/required',
                        keyword: 'required',
                        params: { missingProperty: missing0 },
                        message: "must have required property '" + missing0 + "'",
                    },
                ]
                return false
            } else {
                const _errs1 = errors
                for (const key0 in data) {
                    if (
                        !(
                            key0 === 'key' ||
                            key0 === 'label' ||
                            key0 === 'operator' ||
                            key0 === 'type' ||
                            key0 === 'value'
                        )
                    ) {
                        validate19.errors = [
                            {
                                instancePath,
                                schemaPath: '#/additionalProperties',
                                keyword: 'additionalProperties',
                                params: { additionalProperty: key0 },
                                message: 'must NOT have additional properties',
                            },
                        ]
                        return false
                        break
                    }
                }
                if (_errs1 === errors) {
                    if (data.key !== undefined) {
                        let data0 = data.key
                        const _errs2 = errors
                        if (typeof data0 !== 'string') {
                            validate19.errors = [
                                {
                                    instancePath: instancePath + '/key',
                                    schemaPath: '#/properties/key/type',
                                    keyword: 'type',
                                    params: { type: 'string' },
                                    message: 'must be string',
                                },
                            ]
                            return false
                        }
                        if (!(data0 === 'tag_name' || data0 === 'text' || data0 === 'href' || data0 === 'selector')) {
                            validate19.errors = [
                                {
                                    instancePath: instancePath + '/key',
                                    schemaPath: '#/properties/key/enum',
                                    keyword: 'enum',
                                    params: { allowedValues: schema20.properties.key.enum },
                                    message: 'must be equal to one of the allowed values',
                                },
                            ]
                            return false
                        }
                        var valid0 = _errs2 === errors
                    } else {
                        var valid0 = true
                    }
                    if (valid0) {
                        if (data.label !== undefined) {
                            const _errs4 = errors
                            if (typeof data.label !== 'string') {
                                validate19.errors = [
                                    {
                                        instancePath: instancePath + '/label',
                                        schemaPath: '#/properties/label/type',
                                        keyword: 'type',
                                        params: { type: 'string' },
                                        message: 'must be string',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs4 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.operator !== undefined) {
                                let data2 = data.operator
                                const _errs6 = errors
                                if (typeof data2 !== 'string') {
                                    validate19.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/type',
                                            keyword: 'type',
                                            params: { type: 'string' },
                                            message: 'must be string',
                                        },
                                    ]
                                    return false
                                }
                                if (
                                    !(
                                        data2 === 'exact' ||
                                        data2 === 'is_not' ||
                                        data2 === 'icontains' ||
                                        data2 === 'not_icontains' ||
                                        data2 === 'regex' ||
                                        data2 === 'not_regex' ||
                                        data2 === 'gt' ||
                                        data2 === 'gte' ||
                                        data2 === 'lt' ||
                                        data2 === 'lte' ||
                                        data2 === 'is_set' ||
                                        data2 === 'is_not_set' ||
                                        data2 === 'is_date_exact' ||
                                        data2 === 'is_date_before' ||
                                        data2 === 'is_date_after' ||
                                        data2 === 'between' ||
                                        data2 === 'not_between' ||
                                        data2 === 'min' ||
                                        data2 === 'max' ||
                                        data2 === 'in' ||
                                        data2 === 'not_in' ||
                                        data2 === 'is_cleaned_path_exact' ||
                                        data2 === 'flag_evaluates_to'
                                    )
                                ) {
                                    validate19.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/enum',
                                            keyword: 'enum',
                                            params: { allowedValues: schema14.enum },
                                            message: 'must be equal to one of the allowed values',
                                        },
                                    ]
                                    return false
                                }
                                var valid0 = _errs6 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.type !== undefined) {
                                    let data3 = data.type
                                    const _errs9 = errors
                                    if (typeof data3 !== 'string') {
                                        validate19.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/type',
                                                keyword: 'type',
                                                params: { type: 'string' },
                                                message: 'must be string',
                                            },
                                        ]
                                        return false
                                    }
                                    if ('element' !== data3) {
                                        validate19.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/const',
                                                keyword: 'const',
                                                params: { allowedValue: 'element' },
                                                message: 'must be equal to constant',
                                            },
                                        ]
                                        return false
                                    }
                                    var valid0 = _errs9 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.value !== undefined) {
                                        const _errs11 = errors
                                        if (
                                            !validate13(data.value, {
                                                instancePath: instancePath + '/value',
                                                parentData: data,
                                                parentDataProperty: 'value',
                                                rootData,
                                            })
                                        ) {
                                            vErrors =
                                                vErrors === null ? validate13.errors : vErrors.concat(validate13.errors)
                                            errors = vErrors.length
                                        }
                                        var valid0 = _errs11 === errors
                                    } else {
                                        var valid0 = true
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } else {
            validate19.errors = [
                {
                    instancePath,
                    schemaPath: '#/type',
                    keyword: 'type',
                    params: { type: 'object' },
                    message: 'must be object',
                },
            ]
            return false
        }
    }
    validate19.errors = vErrors
    return errors === 0
}
const schema22 = {
    additionalProperties: false,
    properties: {
        key: { type: 'string' },
        label: { type: 'string' },
        operator: { $ref: '#/definitions/PropertyOperator' },
        type: { const: 'event_metadata', type: 'string' },
        value: { $ref: '#/definitions/PropertyFilterValue' },
    },
    required: ['key', 'operator', 'type'],
    type: 'object',
}
function validate22(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if (
                (data.key === undefined && (missing0 = 'key')) ||
                (data.operator === undefined && (missing0 = 'operator')) ||
                (data.type === undefined && (missing0 = 'type'))
            ) {
                validate22.errors = [
                    {
                        instancePath,
                        schemaPath: '#/required',
                        keyword: 'required',
                        params: { missingProperty: missing0 },
                        message: "must have required property '" + missing0 + "'",
                    },
                ]
                return false
            } else {
                const _errs1 = errors
                for (const key0 in data) {
                    if (
                        !(
                            key0 === 'key' ||
                            key0 === 'label' ||
                            key0 === 'operator' ||
                            key0 === 'type' ||
                            key0 === 'value'
                        )
                    ) {
                        validate22.errors = [
                            {
                                instancePath,
                                schemaPath: '#/additionalProperties',
                                keyword: 'additionalProperties',
                                params: { additionalProperty: key0 },
                                message: 'must NOT have additional properties',
                            },
                        ]
                        return false
                        break
                    }
                }
                if (_errs1 === errors) {
                    if (data.key !== undefined) {
                        const _errs2 = errors
                        if (typeof data.key !== 'string') {
                            validate22.errors = [
                                {
                                    instancePath: instancePath + '/key',
                                    schemaPath: '#/properties/key/type',
                                    keyword: 'type',
                                    params: { type: 'string' },
                                    message: 'must be string',
                                },
                            ]
                            return false
                        }
                        var valid0 = _errs2 === errors
                    } else {
                        var valid0 = true
                    }
                    if (valid0) {
                        if (data.label !== undefined) {
                            const _errs4 = errors
                            if (typeof data.label !== 'string') {
                                validate22.errors = [
                                    {
                                        instancePath: instancePath + '/label',
                                        schemaPath: '#/properties/label/type',
                                        keyword: 'type',
                                        params: { type: 'string' },
                                        message: 'must be string',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs4 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.operator !== undefined) {
                                let data2 = data.operator
                                const _errs6 = errors
                                if (typeof data2 !== 'string') {
                                    validate22.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/type',
                                            keyword: 'type',
                                            params: { type: 'string' },
                                            message: 'must be string',
                                        },
                                    ]
                                    return false
                                }
                                if (
                                    !(
                                        data2 === 'exact' ||
                                        data2 === 'is_not' ||
                                        data2 === 'icontains' ||
                                        data2 === 'not_icontains' ||
                                        data2 === 'regex' ||
                                        data2 === 'not_regex' ||
                                        data2 === 'gt' ||
                                        data2 === 'gte' ||
                                        data2 === 'lt' ||
                                        data2 === 'lte' ||
                                        data2 === 'is_set' ||
                                        data2 === 'is_not_set' ||
                                        data2 === 'is_date_exact' ||
                                        data2 === 'is_date_before' ||
                                        data2 === 'is_date_after' ||
                                        data2 === 'between' ||
                                        data2 === 'not_between' ||
                                        data2 === 'min' ||
                                        data2 === 'max' ||
                                        data2 === 'in' ||
                                        data2 === 'not_in' ||
                                        data2 === 'is_cleaned_path_exact' ||
                                        data2 === 'flag_evaluates_to'
                                    )
                                ) {
                                    validate22.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/enum',
                                            keyword: 'enum',
                                            params: { allowedValues: schema14.enum },
                                            message: 'must be equal to one of the allowed values',
                                        },
                                    ]
                                    return false
                                }
                                var valid0 = _errs6 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.type !== undefined) {
                                    let data3 = data.type
                                    const _errs9 = errors
                                    if (typeof data3 !== 'string') {
                                        validate22.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/type',
                                                keyword: 'type',
                                                params: { type: 'string' },
                                                message: 'must be string',
                                            },
                                        ]
                                        return false
                                    }
                                    if ('event_metadata' !== data3) {
                                        validate22.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/const',
                                                keyword: 'const',
                                                params: { allowedValue: 'event_metadata' },
                                                message: 'must be equal to constant',
                                            },
                                        ]
                                        return false
                                    }
                                    var valid0 = _errs9 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.value !== undefined) {
                                        const _errs11 = errors
                                        if (
                                            !validate13(data.value, {
                                                instancePath: instancePath + '/value',
                                                parentData: data,
                                                parentDataProperty: 'value',
                                                rootData,
                                            })
                                        ) {
                                            vErrors =
                                                vErrors === null ? validate13.errors : vErrors.concat(validate13.errors)
                                            errors = vErrors.length
                                        }
                                        var valid0 = _errs11 === errors
                                    } else {
                                        var valid0 = true
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } else {
            validate22.errors = [
                {
                    instancePath,
                    schemaPath: '#/type',
                    keyword: 'type',
                    params: { type: 'object' },
                    message: 'must be object',
                },
            ]
            return false
        }
    }
    validate22.errors = vErrors
    return errors === 0
}
const schema24 = {
    additionalProperties: false,
    properties: {
        key: { type: 'string' },
        label: { type: 'string' },
        operator: { $ref: '#/definitions/PropertyOperator' },
        type: { const: 'session', type: 'string' },
        value: { $ref: '#/definitions/PropertyFilterValue' },
    },
    required: ['key', 'operator', 'type'],
    type: 'object',
}
function validate25(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if (
                (data.key === undefined && (missing0 = 'key')) ||
                (data.operator === undefined && (missing0 = 'operator')) ||
                (data.type === undefined && (missing0 = 'type'))
            ) {
                validate25.errors = [
                    {
                        instancePath,
                        schemaPath: '#/required',
                        keyword: 'required',
                        params: { missingProperty: missing0 },
                        message: "must have required property '" + missing0 + "'",
                    },
                ]
                return false
            } else {
                const _errs1 = errors
                for (const key0 in data) {
                    if (
                        !(
                            key0 === 'key' ||
                            key0 === 'label' ||
                            key0 === 'operator' ||
                            key0 === 'type' ||
                            key0 === 'value'
                        )
                    ) {
                        validate25.errors = [
                            {
                                instancePath,
                                schemaPath: '#/additionalProperties',
                                keyword: 'additionalProperties',
                                params: { additionalProperty: key0 },
                                message: 'must NOT have additional properties',
                            },
                        ]
                        return false
                        break
                    }
                }
                if (_errs1 === errors) {
                    if (data.key !== undefined) {
                        const _errs2 = errors
                        if (typeof data.key !== 'string') {
                            validate25.errors = [
                                {
                                    instancePath: instancePath + '/key',
                                    schemaPath: '#/properties/key/type',
                                    keyword: 'type',
                                    params: { type: 'string' },
                                    message: 'must be string',
                                },
                            ]
                            return false
                        }
                        var valid0 = _errs2 === errors
                    } else {
                        var valid0 = true
                    }
                    if (valid0) {
                        if (data.label !== undefined) {
                            const _errs4 = errors
                            if (typeof data.label !== 'string') {
                                validate25.errors = [
                                    {
                                        instancePath: instancePath + '/label',
                                        schemaPath: '#/properties/label/type',
                                        keyword: 'type',
                                        params: { type: 'string' },
                                        message: 'must be string',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs4 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.operator !== undefined) {
                                let data2 = data.operator
                                const _errs6 = errors
                                if (typeof data2 !== 'string') {
                                    validate25.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/type',
                                            keyword: 'type',
                                            params: { type: 'string' },
                                            message: 'must be string',
                                        },
                                    ]
                                    return false
                                }
                                if (
                                    !(
                                        data2 === 'exact' ||
                                        data2 === 'is_not' ||
                                        data2 === 'icontains' ||
                                        data2 === 'not_icontains' ||
                                        data2 === 'regex' ||
                                        data2 === 'not_regex' ||
                                        data2 === 'gt' ||
                                        data2 === 'gte' ||
                                        data2 === 'lt' ||
                                        data2 === 'lte' ||
                                        data2 === 'is_set' ||
                                        data2 === 'is_not_set' ||
                                        data2 === 'is_date_exact' ||
                                        data2 === 'is_date_before' ||
                                        data2 === 'is_date_after' ||
                                        data2 === 'between' ||
                                        data2 === 'not_between' ||
                                        data2 === 'min' ||
                                        data2 === 'max' ||
                                        data2 === 'in' ||
                                        data2 === 'not_in' ||
                                        data2 === 'is_cleaned_path_exact' ||
                                        data2 === 'flag_evaluates_to'
                                    )
                                ) {
                                    validate25.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/enum',
                                            keyword: 'enum',
                                            params: { allowedValues: schema14.enum },
                                            message: 'must be equal to one of the allowed values',
                                        },
                                    ]
                                    return false
                                }
                                var valid0 = _errs6 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.type !== undefined) {
                                    let data3 = data.type
                                    const _errs9 = errors
                                    if (typeof data3 !== 'string') {
                                        validate25.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/type',
                                                keyword: 'type',
                                                params: { type: 'string' },
                                                message: 'must be string',
                                            },
                                        ]
                                        return false
                                    }
                                    if ('session' !== data3) {
                                        validate25.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/const',
                                                keyword: 'const',
                                                params: { allowedValue: 'session' },
                                                message: 'must be equal to constant',
                                            },
                                        ]
                                        return false
                                    }
                                    var valid0 = _errs9 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.value !== undefined) {
                                        const _errs11 = errors
                                        if (
                                            !validate13(data.value, {
                                                instancePath: instancePath + '/value',
                                                parentData: data,
                                                parentDataProperty: 'value',
                                                rootData,
                                            })
                                        ) {
                                            vErrors =
                                                vErrors === null ? validate13.errors : vErrors.concat(validate13.errors)
                                            errors = vErrors.length
                                        }
                                        var valid0 = _errs11 === errors
                                    } else {
                                        var valid0 = true
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } else {
            validate25.errors = [
                {
                    instancePath,
                    schemaPath: '#/type',
                    keyword: 'type',
                    params: { type: 'object' },
                    message: 'must be object',
                },
            ]
            return false
        }
    }
    validate25.errors = vErrors
    return errors === 0
}
const schema26 = {
    additionalProperties: false,
    description: 'Sync with plugin-server/src/types.ts',
    properties: {
        cohort_name: { type: 'string' },
        key: { const: 'id', type: 'string' },
        label: { type: 'string' },
        operator: { $ref: '#/definitions/PropertyOperator', default: 'in' },
        type: { const: 'cohort', type: 'string' },
        value: { type: 'integer' },
    },
    required: ['key', 'operator', 'type', 'value'],
    type: 'object',
}
function validate28(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if (
                (data.key === undefined && (missing0 = 'key')) ||
                (data.operator === undefined && (missing0 = 'operator')) ||
                (data.type === undefined && (missing0 = 'type')) ||
                (data.value === undefined && (missing0 = 'value'))
            ) {
                validate28.errors = [
                    {
                        instancePath,
                        schemaPath: '#/required',
                        keyword: 'required',
                        params: { missingProperty: missing0 },
                        message: "must have required property '" + missing0 + "'",
                    },
                ]
                return false
            } else {
                const _errs1 = errors
                for (const key0 in data) {
                    if (
                        !(
                            key0 === 'cohort_name' ||
                            key0 === 'key' ||
                            key0 === 'label' ||
                            key0 === 'operator' ||
                            key0 === 'type' ||
                            key0 === 'value'
                        )
                    ) {
                        validate28.errors = [
                            {
                                instancePath,
                                schemaPath: '#/additionalProperties',
                                keyword: 'additionalProperties',
                                params: { additionalProperty: key0 },
                                message: 'must NOT have additional properties',
                            },
                        ]
                        return false
                        break
                    }
                }
                if (_errs1 === errors) {
                    if (data.cohort_name !== undefined) {
                        const _errs2 = errors
                        if (typeof data.cohort_name !== 'string') {
                            validate28.errors = [
                                {
                                    instancePath: instancePath + '/cohort_name',
                                    schemaPath: '#/properties/cohort_name/type',
                                    keyword: 'type',
                                    params: { type: 'string' },
                                    message: 'must be string',
                                },
                            ]
                            return false
                        }
                        var valid0 = _errs2 === errors
                    } else {
                        var valid0 = true
                    }
                    if (valid0) {
                        if (data.key !== undefined) {
                            let data1 = data.key
                            const _errs4 = errors
                            if (typeof data1 !== 'string') {
                                validate28.errors = [
                                    {
                                        instancePath: instancePath + '/key',
                                        schemaPath: '#/properties/key/type',
                                        keyword: 'type',
                                        params: { type: 'string' },
                                        message: 'must be string',
                                    },
                                ]
                                return false
                            }
                            if ('id' !== data1) {
                                validate28.errors = [
                                    {
                                        instancePath: instancePath + '/key',
                                        schemaPath: '#/properties/key/const',
                                        keyword: 'const',
                                        params: { allowedValue: 'id' },
                                        message: 'must be equal to constant',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs4 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.label !== undefined) {
                                const _errs6 = errors
                                if (typeof data.label !== 'string') {
                                    validate28.errors = [
                                        {
                                            instancePath: instancePath + '/label',
                                            schemaPath: '#/properties/label/type',
                                            keyword: 'type',
                                            params: { type: 'string' },
                                            message: 'must be string',
                                        },
                                    ]
                                    return false
                                }
                                var valid0 = _errs6 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.operator !== undefined) {
                                    let data3 = data.operator
                                    const _errs8 = errors
                                    if (typeof data3 !== 'string') {
                                        validate28.errors = [
                                            {
                                                instancePath: instancePath + '/operator',
                                                schemaPath: '#/definitions/PropertyOperator/type',
                                                keyword: 'type',
                                                params: { type: 'string' },
                                                message: 'must be string',
                                            },
                                        ]
                                        return false
                                    }
                                    if (
                                        !(
                                            data3 === 'exact' ||
                                            data3 === 'is_not' ||
                                            data3 === 'icontains' ||
                                            data3 === 'not_icontains' ||
                                            data3 === 'regex' ||
                                            data3 === 'not_regex' ||
                                            data3 === 'gt' ||
                                            data3 === 'gte' ||
                                            data3 === 'lt' ||
                                            data3 === 'lte' ||
                                            data3 === 'is_set' ||
                                            data3 === 'is_not_set' ||
                                            data3 === 'is_date_exact' ||
                                            data3 === 'is_date_before' ||
                                            data3 === 'is_date_after' ||
                                            data3 === 'between' ||
                                            data3 === 'not_between' ||
                                            data3 === 'min' ||
                                            data3 === 'max' ||
                                            data3 === 'in' ||
                                            data3 === 'not_in' ||
                                            data3 === 'is_cleaned_path_exact' ||
                                            data3 === 'flag_evaluates_to'
                                        )
                                    ) {
                                        validate28.errors = [
                                            {
                                                instancePath: instancePath + '/operator',
                                                schemaPath: '#/definitions/PropertyOperator/enum',
                                                keyword: 'enum',
                                                params: { allowedValues: schema14.enum },
                                                message: 'must be equal to one of the allowed values',
                                            },
                                        ]
                                        return false
                                    }
                                    var valid0 = _errs8 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.type !== undefined) {
                                        let data4 = data.type
                                        const _errs11 = errors
                                        if (typeof data4 !== 'string') {
                                            validate28.errors = [
                                                {
                                                    instancePath: instancePath + '/type',
                                                    schemaPath: '#/properties/type/type',
                                                    keyword: 'type',
                                                    params: { type: 'string' },
                                                    message: 'must be string',
                                                },
                                            ]
                                            return false
                                        }
                                        if ('cohort' !== data4) {
                                            validate28.errors = [
                                                {
                                                    instancePath: instancePath + '/type',
                                                    schemaPath: '#/properties/type/const',
                                                    keyword: 'const',
                                                    params: { allowedValue: 'cohort' },
                                                    message: 'must be equal to constant',
                                                },
                                            ]
                                            return false
                                        }
                                        var valid0 = _errs11 === errors
                                    } else {
                                        var valid0 = true
                                    }
                                    if (valid0) {
                                        if (data.value !== undefined) {
                                            let data5 = data.value
                                            const _errs13 = errors
                                            if (
                                                !(
                                                    typeof data5 == 'number' &&
                                                    !(data5 % 1) &&
                                                    !isNaN(data5) &&
                                                    isFinite(data5)
                                                )
                                            ) {
                                                validate28.errors = [
                                                    {
                                                        instancePath: instancePath + '/value',
                                                        schemaPath: '#/properties/value/type',
                                                        keyword: 'type',
                                                        params: { type: 'integer' },
                                                        message: 'must be integer',
                                                    },
                                                ]
                                                return false
                                            }
                                            var valid0 = _errs13 === errors
                                        } else {
                                            var valid0 = true
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } else {
            validate28.errors = [
                {
                    instancePath,
                    schemaPath: '#/type',
                    keyword: 'type',
                    params: { type: 'object' },
                    message: 'must be object',
                },
            ]
            return false
        }
    }
    validate28.errors = vErrors
    return errors === 0
}
const schema28 = {
    additionalProperties: false,
    properties: {
        key: {
            anyOf: [
                { $ref: '#/definitions/DurationType' },
                { const: 'snapshot_source', type: 'string' },
                { const: 'visited_page', type: 'string' },
                { const: 'comment_text', type: 'string' },
            ],
        },
        label: { type: 'string' },
        operator: { $ref: '#/definitions/PropertyOperator' },
        type: { const: 'recording', type: 'string' },
        value: { $ref: '#/definitions/PropertyFilterValue' },
    },
    required: ['key', 'operator', 'type'],
    type: 'object',
}
const schema29 = { enum: ['duration', 'active_seconds', 'inactive_seconds'], type: 'string' }
function validate30(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if (
                (data.key === undefined && (missing0 = 'key')) ||
                (data.operator === undefined && (missing0 = 'operator')) ||
                (data.type === undefined && (missing0 = 'type'))
            ) {
                validate30.errors = [
                    {
                        instancePath,
                        schemaPath: '#/required',
                        keyword: 'required',
                        params: { missingProperty: missing0 },
                        message: "must have required property '" + missing0 + "'",
                    },
                ]
                return false
            } else {
                const _errs1 = errors
                for (const key0 in data) {
                    if (
                        !(
                            key0 === 'key' ||
                            key0 === 'label' ||
                            key0 === 'operator' ||
                            key0 === 'type' ||
                            key0 === 'value'
                        )
                    ) {
                        validate30.errors = [
                            {
                                instancePath,
                                schemaPath: '#/additionalProperties',
                                keyword: 'additionalProperties',
                                params: { additionalProperty: key0 },
                                message: 'must NOT have additional properties',
                            },
                        ]
                        return false
                        break
                    }
                }
                if (_errs1 === errors) {
                    if (data.key !== undefined) {
                        let data0 = data.key
                        const _errs2 = errors
                        const _errs3 = errors
                        let valid1 = false
                        const _errs4 = errors
                        if (typeof data0 !== 'string') {
                            const err0 = {
                                instancePath: instancePath + '/key',
                                schemaPath: '#/definitions/DurationType/type',
                                keyword: 'type',
                                params: { type: 'string' },
                                message: 'must be string',
                            }
                            if (vErrors === null) {
                                vErrors = [err0]
                            } else {
                                vErrors.push(err0)
                            }
                            errors++
                        }
                        if (!(data0 === 'duration' || data0 === 'active_seconds' || data0 === 'inactive_seconds')) {
                            const err1 = {
                                instancePath: instancePath + '/key',
                                schemaPath: '#/definitions/DurationType/enum',
                                keyword: 'enum',
                                params: { allowedValues: schema29.enum },
                                message: 'must be equal to one of the allowed values',
                            }
                            if (vErrors === null) {
                                vErrors = [err1]
                            } else {
                                vErrors.push(err1)
                            }
                            errors++
                        }
                        var _valid0 = _errs4 === errors
                        valid1 = valid1 || _valid0
                        if (!valid1) {
                            const _errs7 = errors
                            if (typeof data0 !== 'string') {
                                const err2 = {
                                    instancePath: instancePath + '/key',
                                    schemaPath: '#/properties/key/anyOf/1/type',
                                    keyword: 'type',
                                    params: { type: 'string' },
                                    message: 'must be string',
                                }
                                if (vErrors === null) {
                                    vErrors = [err2]
                                } else {
                                    vErrors.push(err2)
                                }
                                errors++
                            }
                            if ('snapshot_source' !== data0) {
                                const err3 = {
                                    instancePath: instancePath + '/key',
                                    schemaPath: '#/properties/key/anyOf/1/const',
                                    keyword: 'const',
                                    params: { allowedValue: 'snapshot_source' },
                                    message: 'must be equal to constant',
                                }
                                if (vErrors === null) {
                                    vErrors = [err3]
                                } else {
                                    vErrors.push(err3)
                                }
                                errors++
                            }
                            var _valid0 = _errs7 === errors
                            valid1 = valid1 || _valid0
                            if (!valid1) {
                                const _errs9 = errors
                                if (typeof data0 !== 'string') {
                                    const err4 = {
                                        instancePath: instancePath + '/key',
                                        schemaPath: '#/properties/key/anyOf/2/type',
                                        keyword: 'type',
                                        params: { type: 'string' },
                                        message: 'must be string',
                                    }
                                    if (vErrors === null) {
                                        vErrors = [err4]
                                    } else {
                                        vErrors.push(err4)
                                    }
                                    errors++
                                }
                                if ('visited_page' !== data0) {
                                    const err5 = {
                                        instancePath: instancePath + '/key',
                                        schemaPath: '#/properties/key/anyOf/2/const',
                                        keyword: 'const',
                                        params: { allowedValue: 'visited_page' },
                                        message: 'must be equal to constant',
                                    }
                                    if (vErrors === null) {
                                        vErrors = [err5]
                                    } else {
                                        vErrors.push(err5)
                                    }
                                    errors++
                                }
                                var _valid0 = _errs9 === errors
                                valid1 = valid1 || _valid0
                                if (!valid1) {
                                    const _errs11 = errors
                                    if (typeof data0 !== 'string') {
                                        const err6 = {
                                            instancePath: instancePath + '/key',
                                            schemaPath: '#/properties/key/anyOf/3/type',
                                            keyword: 'type',
                                            params: { type: 'string' },
                                            message: 'must be string',
                                        }
                                        if (vErrors === null) {
                                            vErrors = [err6]
                                        } else {
                                            vErrors.push(err6)
                                        }
                                        errors++
                                    }
                                    if ('comment_text' !== data0) {
                                        const err7 = {
                                            instancePath: instancePath + '/key',
                                            schemaPath: '#/properties/key/anyOf/3/const',
                                            keyword: 'const',
                                            params: { allowedValue: 'comment_text' },
                                            message: 'must be equal to constant',
                                        }
                                        if (vErrors === null) {
                                            vErrors = [err7]
                                        } else {
                                            vErrors.push(err7)
                                        }
                                        errors++
                                    }
                                    var _valid0 = _errs11 === errors
                                    valid1 = valid1 || _valid0
                                }
                            }
                        }
                        if (!valid1) {
                            const err8 = {
                                instancePath: instancePath + '/key',
                                schemaPath: '#/properties/key/anyOf',
                                keyword: 'anyOf',
                                params: {},
                                message: 'must match a schema in anyOf',
                            }
                            if (vErrors === null) {
                                vErrors = [err8]
                            } else {
                                vErrors.push(err8)
                            }
                            errors++
                            validate30.errors = vErrors
                            return false
                        } else {
                            errors = _errs3
                            if (vErrors !== null) {
                                if (_errs3) {
                                    vErrors.length = _errs3
                                } else {
                                    vErrors = null
                                }
                            }
                        }
                        var valid0 = _errs2 === errors
                    } else {
                        var valid0 = true
                    }
                    if (valid0) {
                        if (data.label !== undefined) {
                            const _errs13 = errors
                            if (typeof data.label !== 'string') {
                                validate30.errors = [
                                    {
                                        instancePath: instancePath + '/label',
                                        schemaPath: '#/properties/label/type',
                                        keyword: 'type',
                                        params: { type: 'string' },
                                        message: 'must be string',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs13 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.operator !== undefined) {
                                let data2 = data.operator
                                const _errs15 = errors
                                if (typeof data2 !== 'string') {
                                    validate30.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/type',
                                            keyword: 'type',
                                            params: { type: 'string' },
                                            message: 'must be string',
                                        },
                                    ]
                                    return false
                                }
                                if (
                                    !(
                                        data2 === 'exact' ||
                                        data2 === 'is_not' ||
                                        data2 === 'icontains' ||
                                        data2 === 'not_icontains' ||
                                        data2 === 'regex' ||
                                        data2 === 'not_regex' ||
                                        data2 === 'gt' ||
                                        data2 === 'gte' ||
                                        data2 === 'lt' ||
                                        data2 === 'lte' ||
                                        data2 === 'is_set' ||
                                        data2 === 'is_not_set' ||
                                        data2 === 'is_date_exact' ||
                                        data2 === 'is_date_before' ||
                                        data2 === 'is_date_after' ||
                                        data2 === 'between' ||
                                        data2 === 'not_between' ||
                                        data2 === 'min' ||
                                        data2 === 'max' ||
                                        data2 === 'in' ||
                                        data2 === 'not_in' ||
                                        data2 === 'is_cleaned_path_exact' ||
                                        data2 === 'flag_evaluates_to'
                                    )
                                ) {
                                    validate30.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/enum',
                                            keyword: 'enum',
                                            params: { allowedValues: schema14.enum },
                                            message: 'must be equal to one of the allowed values',
                                        },
                                    ]
                                    return false
                                }
                                var valid0 = _errs15 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.type !== undefined) {
                                    let data3 = data.type
                                    const _errs18 = errors
                                    if (typeof data3 !== 'string') {
                                        validate30.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/type',
                                                keyword: 'type',
                                                params: { type: 'string' },
                                                message: 'must be string',
                                            },
                                        ]
                                        return false
                                    }
                                    if ('recording' !== data3) {
                                        validate30.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/const',
                                                keyword: 'const',
                                                params: { allowedValue: 'recording' },
                                                message: 'must be equal to constant',
                                            },
                                        ]
                                        return false
                                    }
                                    var valid0 = _errs18 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.value !== undefined) {
                                        const _errs20 = errors
                                        if (
                                            !validate13(data.value, {
                                                instancePath: instancePath + '/value',
                                                parentData: data,
                                                parentDataProperty: 'value',
                                                rootData,
                                            })
                                        ) {
                                            vErrors =
                                                vErrors === null ? validate13.errors : vErrors.concat(validate13.errors)
                                            errors = vErrors.length
                                        }
                                        var valid0 = _errs20 === errors
                                    } else {
                                        var valid0 = true
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } else {
            validate30.errors = [
                {
                    instancePath,
                    schemaPath: '#/type',
                    keyword: 'type',
                    params: { type: 'object' },
                    message: 'must be object',
                },
            ]
            return false
        }
    }
    validate30.errors = vErrors
    return errors === 0
}
const schema31 = {
    additionalProperties: false,
    properties: {
        key: { type: 'string' },
        label: { type: 'string' },
        operator: { $ref: '#/definitions/PropertyOperator' },
        type: { const: 'log_entry', type: 'string' },
        value: { $ref: '#/definitions/PropertyFilterValue' },
    },
    required: ['key', 'operator', 'type'],
    type: 'object',
}
function validate33(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if (
                (data.key === undefined && (missing0 = 'key')) ||
                (data.operator === undefined && (missing0 = 'operator')) ||
                (data.type === undefined && (missing0 = 'type'))
            ) {
                validate33.errors = [
                    {
                        instancePath,
                        schemaPath: '#/required',
                        keyword: 'required',
                        params: { missingProperty: missing0 },
                        message: "must have required property '" + missing0 + "'",
                    },
                ]
                return false
            } else {
                const _errs1 = errors
                for (const key0 in data) {
                    if (
                        !(
                            key0 === 'key' ||
                            key0 === 'label' ||
                            key0 === 'operator' ||
                            key0 === 'type' ||
                            key0 === 'value'
                        )
                    ) {
                        validate33.errors = [
                            {
                                instancePath,
                                schemaPath: '#/additionalProperties',
                                keyword: 'additionalProperties',
                                params: { additionalProperty: key0 },
                                message: 'must NOT have additional properties',
                            },
                        ]
                        return false
                        break
                    }
                }
                if (_errs1 === errors) {
                    if (data.key !== undefined) {
                        const _errs2 = errors
                        if (typeof data.key !== 'string') {
                            validate33.errors = [
                                {
                                    instancePath: instancePath + '/key',
                                    schemaPath: '#/properties/key/type',
                                    keyword: 'type',
                                    params: { type: 'string' },
                                    message: 'must be string',
                                },
                            ]
                            return false
                        }
                        var valid0 = _errs2 === errors
                    } else {
                        var valid0 = true
                    }
                    if (valid0) {
                        if (data.label !== undefined) {
                            const _errs4 = errors
                            if (typeof data.label !== 'string') {
                                validate33.errors = [
                                    {
                                        instancePath: instancePath + '/label',
                                        schemaPath: '#/properties/label/type',
                                        keyword: 'type',
                                        params: { type: 'string' },
                                        message: 'must be string',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs4 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.operator !== undefined) {
                                let data2 = data.operator
                                const _errs6 = errors
                                if (typeof data2 !== 'string') {
                                    validate33.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/type',
                                            keyword: 'type',
                                            params: { type: 'string' },
                                            message: 'must be string',
                                        },
                                    ]
                                    return false
                                }
                                if (
                                    !(
                                        data2 === 'exact' ||
                                        data2 === 'is_not' ||
                                        data2 === 'icontains' ||
                                        data2 === 'not_icontains' ||
                                        data2 === 'regex' ||
                                        data2 === 'not_regex' ||
                                        data2 === 'gt' ||
                                        data2 === 'gte' ||
                                        data2 === 'lt' ||
                                        data2 === 'lte' ||
                                        data2 === 'is_set' ||
                                        data2 === 'is_not_set' ||
                                        data2 === 'is_date_exact' ||
                                        data2 === 'is_date_before' ||
                                        data2 === 'is_date_after' ||
                                        data2 === 'between' ||
                                        data2 === 'not_between' ||
                                        data2 === 'min' ||
                                        data2 === 'max' ||
                                        data2 === 'in' ||
                                        data2 === 'not_in' ||
                                        data2 === 'is_cleaned_path_exact' ||
                                        data2 === 'flag_evaluates_to'
                                    )
                                ) {
                                    validate33.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/enum',
                                            keyword: 'enum',
                                            params: { allowedValues: schema14.enum },
                                            message: 'must be equal to one of the allowed values',
                                        },
                                    ]
                                    return false
                                }
                                var valid0 = _errs6 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.type !== undefined) {
                                    let data3 = data.type
                                    const _errs9 = errors
                                    if (typeof data3 !== 'string') {
                                        validate33.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/type',
                                                keyword: 'type',
                                                params: { type: 'string' },
                                                message: 'must be string',
                                            },
                                        ]
                                        return false
                                    }
                                    if ('log_entry' !== data3) {
                                        validate33.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/const',
                                                keyword: 'const',
                                                params: { allowedValue: 'log_entry' },
                                                message: 'must be equal to constant',
                                            },
                                        ]
                                        return false
                                    }
                                    var valid0 = _errs9 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.value !== undefined) {
                                        const _errs11 = errors
                                        if (
                                            !validate13(data.value, {
                                                instancePath: instancePath + '/value',
                                                parentData: data,
                                                parentDataProperty: 'value',
                                                rootData,
                                            })
                                        ) {
                                            vErrors =
                                                vErrors === null ? validate13.errors : vErrors.concat(validate13.errors)
                                            errors = vErrors.length
                                        }
                                        var valid0 = _errs11 === errors
                                    } else {
                                        var valid0 = true
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } else {
            validate33.errors = [
                {
                    instancePath,
                    schemaPath: '#/type',
                    keyword: 'type',
                    params: { type: 'object' },
                    message: 'must be object',
                },
            ]
            return false
        }
    }
    validate33.errors = vErrors
    return errors === 0
}
const schema33 = {
    additionalProperties: false,
    properties: {
        group_type_index: { anyOf: [{ type: 'integer' }, { type: 'null' }] },
        key: { type: 'string' },
        label: { type: 'string' },
        operator: { $ref: '#/definitions/PropertyOperator' },
        type: { const: 'group', type: 'string' },
        value: { $ref: '#/definitions/PropertyFilterValue' },
    },
    required: ['key', 'operator', 'type'],
    type: 'object',
}
function validate36(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if (
                (data.key === undefined && (missing0 = 'key')) ||
                (data.operator === undefined && (missing0 = 'operator')) ||
                (data.type === undefined && (missing0 = 'type'))
            ) {
                validate36.errors = [
                    {
                        instancePath,
                        schemaPath: '#/required',
                        keyword: 'required',
                        params: { missingProperty: missing0 },
                        message: "must have required property '" + missing0 + "'",
                    },
                ]
                return false
            } else {
                const _errs1 = errors
                for (const key0 in data) {
                    if (
                        !(
                            key0 === 'group_type_index' ||
                            key0 === 'key' ||
                            key0 === 'label' ||
                            key0 === 'operator' ||
                            key0 === 'type' ||
                            key0 === 'value'
                        )
                    ) {
                        validate36.errors = [
                            {
                                instancePath,
                                schemaPath: '#/additionalProperties',
                                keyword: 'additionalProperties',
                                params: { additionalProperty: key0 },
                                message: 'must NOT have additional properties',
                            },
                        ]
                        return false
                        break
                    }
                }
                if (_errs1 === errors) {
                    if (data.group_type_index !== undefined) {
                        let data0 = data.group_type_index
                        const _errs2 = errors
                        const _errs3 = errors
                        let valid1 = false
                        const _errs4 = errors
                        if (!(typeof data0 == 'number' && !(data0 % 1) && !isNaN(data0) && isFinite(data0))) {
                            const err0 = {
                                instancePath: instancePath + '/group_type_index',
                                schemaPath: '#/properties/group_type_index/anyOf/0/type',
                                keyword: 'type',
                                params: { type: 'integer' },
                                message: 'must be integer',
                            }
                            if (vErrors === null) {
                                vErrors = [err0]
                            } else {
                                vErrors.push(err0)
                            }
                            errors++
                        }
                        var _valid0 = _errs4 === errors
                        valid1 = valid1 || _valid0
                        if (!valid1) {
                            const _errs6 = errors
                            if (data0 !== null) {
                                const err1 = {
                                    instancePath: instancePath + '/group_type_index',
                                    schemaPath: '#/properties/group_type_index/anyOf/1/type',
                                    keyword: 'type',
                                    params: { type: 'null' },
                                    message: 'must be null',
                                }
                                if (vErrors === null) {
                                    vErrors = [err1]
                                } else {
                                    vErrors.push(err1)
                                }
                                errors++
                            }
                            var _valid0 = _errs6 === errors
                            valid1 = valid1 || _valid0
                        }
                        if (!valid1) {
                            const err2 = {
                                instancePath: instancePath + '/group_type_index',
                                schemaPath: '#/properties/group_type_index/anyOf',
                                keyword: 'anyOf',
                                params: {},
                                message: 'must match a schema in anyOf',
                            }
                            if (vErrors === null) {
                                vErrors = [err2]
                            } else {
                                vErrors.push(err2)
                            }
                            errors++
                            validate36.errors = vErrors
                            return false
                        } else {
                            errors = _errs3
                            if (vErrors !== null) {
                                if (_errs3) {
                                    vErrors.length = _errs3
                                } else {
                                    vErrors = null
                                }
                            }
                        }
                        var valid0 = _errs2 === errors
                    } else {
                        var valid0 = true
                    }
                    if (valid0) {
                        if (data.key !== undefined) {
                            const _errs8 = errors
                            if (typeof data.key !== 'string') {
                                validate36.errors = [
                                    {
                                        instancePath: instancePath + '/key',
                                        schemaPath: '#/properties/key/type',
                                        keyword: 'type',
                                        params: { type: 'string' },
                                        message: 'must be string',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs8 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.label !== undefined) {
                                const _errs10 = errors
                                if (typeof data.label !== 'string') {
                                    validate36.errors = [
                                        {
                                            instancePath: instancePath + '/label',
                                            schemaPath: '#/properties/label/type',
                                            keyword: 'type',
                                            params: { type: 'string' },
                                            message: 'must be string',
                                        },
                                    ]
                                    return false
                                }
                                var valid0 = _errs10 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.operator !== undefined) {
                                    let data3 = data.operator
                                    const _errs12 = errors
                                    if (typeof data3 !== 'string') {
                                        validate36.errors = [
                                            {
                                                instancePath: instancePath + '/operator',
                                                schemaPath: '#/definitions/PropertyOperator/type',
                                                keyword: 'type',
                                                params: { type: 'string' },
                                                message: 'must be string',
                                            },
                                        ]
                                        return false
                                    }
                                    if (
                                        !(
                                            data3 === 'exact' ||
                                            data3 === 'is_not' ||
                                            data3 === 'icontains' ||
                                            data3 === 'not_icontains' ||
                                            data3 === 'regex' ||
                                            data3 === 'not_regex' ||
                                            data3 === 'gt' ||
                                            data3 === 'gte' ||
                                            data3 === 'lt' ||
                                            data3 === 'lte' ||
                                            data3 === 'is_set' ||
                                            data3 === 'is_not_set' ||
                                            data3 === 'is_date_exact' ||
                                            data3 === 'is_date_before' ||
                                            data3 === 'is_date_after' ||
                                            data3 === 'between' ||
                                            data3 === 'not_between' ||
                                            data3 === 'min' ||
                                            data3 === 'max' ||
                                            data3 === 'in' ||
                                            data3 === 'not_in' ||
                                            data3 === 'is_cleaned_path_exact' ||
                                            data3 === 'flag_evaluates_to'
                                        )
                                    ) {
                                        validate36.errors = [
                                            {
                                                instancePath: instancePath + '/operator',
                                                schemaPath: '#/definitions/PropertyOperator/enum',
                                                keyword: 'enum',
                                                params: { allowedValues: schema14.enum },
                                                message: 'must be equal to one of the allowed values',
                                            },
                                        ]
                                        return false
                                    }
                                    var valid0 = _errs12 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.type !== undefined) {
                                        let data4 = data.type
                                        const _errs15 = errors
                                        if (typeof data4 !== 'string') {
                                            validate36.errors = [
                                                {
                                                    instancePath: instancePath + '/type',
                                                    schemaPath: '#/properties/type/type',
                                                    keyword: 'type',
                                                    params: { type: 'string' },
                                                    message: 'must be string',
                                                },
                                            ]
                                            return false
                                        }
                                        if ('group' !== data4) {
                                            validate36.errors = [
                                                {
                                                    instancePath: instancePath + '/type',
                                                    schemaPath: '#/properties/type/const',
                                                    keyword: 'const',
                                                    params: { allowedValue: 'group' },
                                                    message: 'must be equal to constant',
                                                },
                                            ]
                                            return false
                                        }
                                        var valid0 = _errs15 === errors
                                    } else {
                                        var valid0 = true
                                    }
                                    if (valid0) {
                                        if (data.value !== undefined) {
                                            const _errs17 = errors
                                            if (
                                                !validate13(data.value, {
                                                    instancePath: instancePath + '/value',
                                                    parentData: data,
                                                    parentDataProperty: 'value',
                                                    rootData,
                                                })
                                            ) {
                                                vErrors =
                                                    vErrors === null
                                                        ? validate13.errors
                                                        : vErrors.concat(validate13.errors)
                                                errors = vErrors.length
                                            }
                                            var valid0 = _errs17 === errors
                                        } else {
                                            var valid0 = true
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } else {
            validate36.errors = [
                {
                    instancePath,
                    schemaPath: '#/type',
                    keyword: 'type',
                    params: { type: 'object' },
                    message: 'must be object',
                },
            ]
            return false
        }
    }
    validate36.errors = vErrors
    return errors === 0
}
const schema35 = {
    additionalProperties: false,
    properties: {
        key: { type: 'string' },
        label: { type: 'string' },
        operator: { $ref: '#/definitions/PropertyOperator' },
        type: { const: 'feature', description: 'Event property with "$feature/" prepended', type: 'string' },
        value: { $ref: '#/definitions/PropertyFilterValue' },
    },
    required: ['key', 'operator', 'type'],
    type: 'object',
}
function validate39(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if (
                (data.key === undefined && (missing0 = 'key')) ||
                (data.operator === undefined && (missing0 = 'operator')) ||
                (data.type === undefined && (missing0 = 'type'))
            ) {
                validate39.errors = [
                    {
                        instancePath,
                        schemaPath: '#/required',
                        keyword: 'required',
                        params: { missingProperty: missing0 },
                        message: "must have required property '" + missing0 + "'",
                    },
                ]
                return false
            } else {
                const _errs1 = errors
                for (const key0 in data) {
                    if (
                        !(
                            key0 === 'key' ||
                            key0 === 'label' ||
                            key0 === 'operator' ||
                            key0 === 'type' ||
                            key0 === 'value'
                        )
                    ) {
                        validate39.errors = [
                            {
                                instancePath,
                                schemaPath: '#/additionalProperties',
                                keyword: 'additionalProperties',
                                params: { additionalProperty: key0 },
                                message: 'must NOT have additional properties',
                            },
                        ]
                        return false
                        break
                    }
                }
                if (_errs1 === errors) {
                    if (data.key !== undefined) {
                        const _errs2 = errors
                        if (typeof data.key !== 'string') {
                            validate39.errors = [
                                {
                                    instancePath: instancePath + '/key',
                                    schemaPath: '#/properties/key/type',
                                    keyword: 'type',
                                    params: { type: 'string' },
                                    message: 'must be string',
                                },
                            ]
                            return false
                        }
                        var valid0 = _errs2 === errors
                    } else {
                        var valid0 = true
                    }
                    if (valid0) {
                        if (data.label !== undefined) {
                            const _errs4 = errors
                            if (typeof data.label !== 'string') {
                                validate39.errors = [
                                    {
                                        instancePath: instancePath + '/label',
                                        schemaPath: '#/properties/label/type',
                                        keyword: 'type',
                                        params: { type: 'string' },
                                        message: 'must be string',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs4 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.operator !== undefined) {
                                let data2 = data.operator
                                const _errs6 = errors
                                if (typeof data2 !== 'string') {
                                    validate39.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/type',
                                            keyword: 'type',
                                            params: { type: 'string' },
                                            message: 'must be string',
                                        },
                                    ]
                                    return false
                                }
                                if (
                                    !(
                                        data2 === 'exact' ||
                                        data2 === 'is_not' ||
                                        data2 === 'icontains' ||
                                        data2 === 'not_icontains' ||
                                        data2 === 'regex' ||
                                        data2 === 'not_regex' ||
                                        data2 === 'gt' ||
                                        data2 === 'gte' ||
                                        data2 === 'lt' ||
                                        data2 === 'lte' ||
                                        data2 === 'is_set' ||
                                        data2 === 'is_not_set' ||
                                        data2 === 'is_date_exact' ||
                                        data2 === 'is_date_before' ||
                                        data2 === 'is_date_after' ||
                                        data2 === 'between' ||
                                        data2 === 'not_between' ||
                                        data2 === 'min' ||
                                        data2 === 'max' ||
                                        data2 === 'in' ||
                                        data2 === 'not_in' ||
                                        data2 === 'is_cleaned_path_exact' ||
                                        data2 === 'flag_evaluates_to'
                                    )
                                ) {
                                    validate39.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/enum',
                                            keyword: 'enum',
                                            params: { allowedValues: schema14.enum },
                                            message: 'must be equal to one of the allowed values',
                                        },
                                    ]
                                    return false
                                }
                                var valid0 = _errs6 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.type !== undefined) {
                                    let data3 = data.type
                                    const _errs9 = errors
                                    if (typeof data3 !== 'string') {
                                        validate39.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/type',
                                                keyword: 'type',
                                                params: { type: 'string' },
                                                message: 'must be string',
                                            },
                                        ]
                                        return false
                                    }
                                    if ('feature' !== data3) {
                                        validate39.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/const',
                                                keyword: 'const',
                                                params: { allowedValue: 'feature' },
                                                message: 'must be equal to constant',
                                            },
                                        ]
                                        return false
                                    }
                                    var valid0 = _errs9 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.value !== undefined) {
                                        const _errs11 = errors
                                        if (
                                            !validate13(data.value, {
                                                instancePath: instancePath + '/value',
                                                parentData: data,
                                                parentDataProperty: 'value',
                                                rootData,
                                            })
                                        ) {
                                            vErrors =
                                                vErrors === null ? validate13.errors : vErrors.concat(validate13.errors)
                                            errors = vErrors.length
                                        }
                                        var valid0 = _errs11 === errors
                                    } else {
                                        var valid0 = true
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } else {
            validate39.errors = [
                {
                    instancePath,
                    schemaPath: '#/type',
                    keyword: 'type',
                    params: { type: 'object' },
                    message: 'must be object',
                },
            ]
            return false
        }
    }
    validate39.errors = vErrors
    return errors === 0
}
const schema38 = {
    additionalProperties: false,
    properties: {
        key: { type: 'string' },
        label: { type: 'string' },
        type: { const: 'hogql', type: 'string' },
        value: { $ref: '#/definitions/PropertyFilterValue' },
    },
    required: ['key', 'type'],
    type: 'object',
}
function validate42(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if ((data.key === undefined && (missing0 = 'key')) || (data.type === undefined && (missing0 = 'type'))) {
                validate42.errors = [
                    {
                        instancePath,
                        schemaPath: '#/required',
                        keyword: 'required',
                        params: { missingProperty: missing0 },
                        message: "must have required property '" + missing0 + "'",
                    },
                ]
                return false
            } else {
                const _errs1 = errors
                for (const key0 in data) {
                    if (!(key0 === 'key' || key0 === 'label' || key0 === 'type' || key0 === 'value')) {
                        validate42.errors = [
                            {
                                instancePath,
                                schemaPath: '#/additionalProperties',
                                keyword: 'additionalProperties',
                                params: { additionalProperty: key0 },
                                message: 'must NOT have additional properties',
                            },
                        ]
                        return false
                        break
                    }
                }
                if (_errs1 === errors) {
                    if (data.key !== undefined) {
                        const _errs2 = errors
                        if (typeof data.key !== 'string') {
                            validate42.errors = [
                                {
                                    instancePath: instancePath + '/key',
                                    schemaPath: '#/properties/key/type',
                                    keyword: 'type',
                                    params: { type: 'string' },
                                    message: 'must be string',
                                },
                            ]
                            return false
                        }
                        var valid0 = _errs2 === errors
                    } else {
                        var valid0 = true
                    }
                    if (valid0) {
                        if (data.label !== undefined) {
                            const _errs4 = errors
                            if (typeof data.label !== 'string') {
                                validate42.errors = [
                                    {
                                        instancePath: instancePath + '/label',
                                        schemaPath: '#/properties/label/type',
                                        keyword: 'type',
                                        params: { type: 'string' },
                                        message: 'must be string',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs4 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.type !== undefined) {
                                let data2 = data.type
                                const _errs6 = errors
                                if (typeof data2 !== 'string') {
                                    validate42.errors = [
                                        {
                                            instancePath: instancePath + '/type',
                                            schemaPath: '#/properties/type/type',
                                            keyword: 'type',
                                            params: { type: 'string' },
                                            message: 'must be string',
                                        },
                                    ]
                                    return false
                                }
                                if ('hogql' !== data2) {
                                    validate42.errors = [
                                        {
                                            instancePath: instancePath + '/type',
                                            schemaPath: '#/properties/type/const',
                                            keyword: 'const',
                                            params: { allowedValue: 'hogql' },
                                            message: 'must be equal to constant',
                                        },
                                    ]
                                    return false
                                }
                                var valid0 = _errs6 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.value !== undefined) {
                                    const _errs8 = errors
                                    if (
                                        !validate13(data.value, {
                                            instancePath: instancePath + '/value',
                                            parentData: data,
                                            parentDataProperty: 'value',
                                            rootData,
                                        })
                                    ) {
                                        vErrors =
                                            vErrors === null ? validate13.errors : vErrors.concat(validate13.errors)
                                        errors = vErrors.length
                                    }
                                    var valid0 = _errs8 === errors
                                } else {
                                    var valid0 = true
                                }
                            }
                        }
                    }
                }
            }
        } else {
            validate42.errors = [
                {
                    instancePath,
                    schemaPath: '#/type',
                    keyword: 'type',
                    params: { type: 'object' },
                    message: 'must be object',
                },
            ]
            return false
        }
    }
    validate42.errors = vErrors
    return errors === 0
}
const schema40 = {
    additionalProperties: false,
    properties: {
        key: { type: 'string' },
        label: { type: 'string' },
        operator: { $ref: '#/definitions/PropertyOperator' },
        type: { const: 'data_warehouse', type: 'string' },
        value: { $ref: '#/definitions/PropertyFilterValue' },
    },
    required: ['key', 'operator', 'type'],
    type: 'object',
}
function validate45(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if (
                (data.key === undefined && (missing0 = 'key')) ||
                (data.operator === undefined && (missing0 = 'operator')) ||
                (data.type === undefined && (missing0 = 'type'))
            ) {
                validate45.errors = [
                    {
                        instancePath,
                        schemaPath: '#/required',
                        keyword: 'required',
                        params: { missingProperty: missing0 },
                        message: "must have required property '" + missing0 + "'",
                    },
                ]
                return false
            } else {
                const _errs1 = errors
                for (const key0 in data) {
                    if (
                        !(
                            key0 === 'key' ||
                            key0 === 'label' ||
                            key0 === 'operator' ||
                            key0 === 'type' ||
                            key0 === 'value'
                        )
                    ) {
                        validate45.errors = [
                            {
                                instancePath,
                                schemaPath: '#/additionalProperties',
                                keyword: 'additionalProperties',
                                params: { additionalProperty: key0 },
                                message: 'must NOT have additional properties',
                            },
                        ]
                        return false
                        break
                    }
                }
                if (_errs1 === errors) {
                    if (data.key !== undefined) {
                        const _errs2 = errors
                        if (typeof data.key !== 'string') {
                            validate45.errors = [
                                {
                                    instancePath: instancePath + '/key',
                                    schemaPath: '#/properties/key/type',
                                    keyword: 'type',
                                    params: { type: 'string' },
                                    message: 'must be string',
                                },
                            ]
                            return false
                        }
                        var valid0 = _errs2 === errors
                    } else {
                        var valid0 = true
                    }
                    if (valid0) {
                        if (data.label !== undefined) {
                            const _errs4 = errors
                            if (typeof data.label !== 'string') {
                                validate45.errors = [
                                    {
                                        instancePath: instancePath + '/label',
                                        schemaPath: '#/properties/label/type',
                                        keyword: 'type',
                                        params: { type: 'string' },
                                        message: 'must be string',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs4 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.operator !== undefined) {
                                let data2 = data.operator
                                const _errs6 = errors
                                if (typeof data2 !== 'string') {
                                    validate45.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/type',
                                            keyword: 'type',
                                            params: { type: 'string' },
                                            message: 'must be string',
                                        },
                                    ]
                                    return false
                                }
                                if (
                                    !(
                                        data2 === 'exact' ||
                                        data2 === 'is_not' ||
                                        data2 === 'icontains' ||
                                        data2 === 'not_icontains' ||
                                        data2 === 'regex' ||
                                        data2 === 'not_regex' ||
                                        data2 === 'gt' ||
                                        data2 === 'gte' ||
                                        data2 === 'lt' ||
                                        data2 === 'lte' ||
                                        data2 === 'is_set' ||
                                        data2 === 'is_not_set' ||
                                        data2 === 'is_date_exact' ||
                                        data2 === 'is_date_before' ||
                                        data2 === 'is_date_after' ||
                                        data2 === 'between' ||
                                        data2 === 'not_between' ||
                                        data2 === 'min' ||
                                        data2 === 'max' ||
                                        data2 === 'in' ||
                                        data2 === 'not_in' ||
                                        data2 === 'is_cleaned_path_exact' ||
                                        data2 === 'flag_evaluates_to'
                                    )
                                ) {
                                    validate45.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/enum',
                                            keyword: 'enum',
                                            params: { allowedValues: schema14.enum },
                                            message: 'must be equal to one of the allowed values',
                                        },
                                    ]
                                    return false
                                }
                                var valid0 = _errs6 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.type !== undefined) {
                                    let data3 = data.type
                                    const _errs9 = errors
                                    if (typeof data3 !== 'string') {
                                        validate45.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/type',
                                                keyword: 'type',
                                                params: { type: 'string' },
                                                message: 'must be string',
                                            },
                                        ]
                                        return false
                                    }
                                    if ('data_warehouse' !== data3) {
                                        validate45.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/const',
                                                keyword: 'const',
                                                params: { allowedValue: 'data_warehouse' },
                                                message: 'must be equal to constant',
                                            },
                                        ]
                                        return false
                                    }
                                    var valid0 = _errs9 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.value !== undefined) {
                                        const _errs11 = errors
                                        if (
                                            !validate13(data.value, {
                                                instancePath: instancePath + '/value',
                                                parentData: data,
                                                parentDataProperty: 'value',
                                                rootData,
                                            })
                                        ) {
                                            vErrors =
                                                vErrors === null ? validate13.errors : vErrors.concat(validate13.errors)
                                            errors = vErrors.length
                                        }
                                        var valid0 = _errs11 === errors
                                    } else {
                                        var valid0 = true
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } else {
            validate45.errors = [
                {
                    instancePath,
                    schemaPath: '#/type',
                    keyword: 'type',
                    params: { type: 'object' },
                    message: 'must be object',
                },
            ]
            return false
        }
    }
    validate45.errors = vErrors
    return errors === 0
}
const schema42 = {
    additionalProperties: false,
    properties: {
        key: { type: 'string' },
        label: { type: 'string' },
        operator: { $ref: '#/definitions/PropertyOperator' },
        type: { const: 'data_warehouse_person_property', type: 'string' },
        value: { $ref: '#/definitions/PropertyFilterValue' },
    },
    required: ['key', 'operator', 'type'],
    type: 'object',
}
function validate48(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if (
                (data.key === undefined && (missing0 = 'key')) ||
                (data.operator === undefined && (missing0 = 'operator')) ||
                (data.type === undefined && (missing0 = 'type'))
            ) {
                validate48.errors = [
                    {
                        instancePath,
                        schemaPath: '#/required',
                        keyword: 'required',
                        params: { missingProperty: missing0 },
                        message: "must have required property '" + missing0 + "'",
                    },
                ]
                return false
            } else {
                const _errs1 = errors
                for (const key0 in data) {
                    if (
                        !(
                            key0 === 'key' ||
                            key0 === 'label' ||
                            key0 === 'operator' ||
                            key0 === 'type' ||
                            key0 === 'value'
                        )
                    ) {
                        validate48.errors = [
                            {
                                instancePath,
                                schemaPath: '#/additionalProperties',
                                keyword: 'additionalProperties',
                                params: { additionalProperty: key0 },
                                message: 'must NOT have additional properties',
                            },
                        ]
                        return false
                        break
                    }
                }
                if (_errs1 === errors) {
                    if (data.key !== undefined) {
                        const _errs2 = errors
                        if (typeof data.key !== 'string') {
                            validate48.errors = [
                                {
                                    instancePath: instancePath + '/key',
                                    schemaPath: '#/properties/key/type',
                                    keyword: 'type',
                                    params: { type: 'string' },
                                    message: 'must be string',
                                },
                            ]
                            return false
                        }
                        var valid0 = _errs2 === errors
                    } else {
                        var valid0 = true
                    }
                    if (valid0) {
                        if (data.label !== undefined) {
                            const _errs4 = errors
                            if (typeof data.label !== 'string') {
                                validate48.errors = [
                                    {
                                        instancePath: instancePath + '/label',
                                        schemaPath: '#/properties/label/type',
                                        keyword: 'type',
                                        params: { type: 'string' },
                                        message: 'must be string',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs4 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.operator !== undefined) {
                                let data2 = data.operator
                                const _errs6 = errors
                                if (typeof data2 !== 'string') {
                                    validate48.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/type',
                                            keyword: 'type',
                                            params: { type: 'string' },
                                            message: 'must be string',
                                        },
                                    ]
                                    return false
                                }
                                if (
                                    !(
                                        data2 === 'exact' ||
                                        data2 === 'is_not' ||
                                        data2 === 'icontains' ||
                                        data2 === 'not_icontains' ||
                                        data2 === 'regex' ||
                                        data2 === 'not_regex' ||
                                        data2 === 'gt' ||
                                        data2 === 'gte' ||
                                        data2 === 'lt' ||
                                        data2 === 'lte' ||
                                        data2 === 'is_set' ||
                                        data2 === 'is_not_set' ||
                                        data2 === 'is_date_exact' ||
                                        data2 === 'is_date_before' ||
                                        data2 === 'is_date_after' ||
                                        data2 === 'between' ||
                                        data2 === 'not_between' ||
                                        data2 === 'min' ||
                                        data2 === 'max' ||
                                        data2 === 'in' ||
                                        data2 === 'not_in' ||
                                        data2 === 'is_cleaned_path_exact' ||
                                        data2 === 'flag_evaluates_to'
                                    )
                                ) {
                                    validate48.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/enum',
                                            keyword: 'enum',
                                            params: { allowedValues: schema14.enum },
                                            message: 'must be equal to one of the allowed values',
                                        },
                                    ]
                                    return false
                                }
                                var valid0 = _errs6 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.type !== undefined) {
                                    let data3 = data.type
                                    const _errs9 = errors
                                    if (typeof data3 !== 'string') {
                                        validate48.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/type',
                                                keyword: 'type',
                                                params: { type: 'string' },
                                                message: 'must be string',
                                            },
                                        ]
                                        return false
                                    }
                                    if ('data_warehouse_person_property' !== data3) {
                                        validate48.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/const',
                                                keyword: 'const',
                                                params: { allowedValue: 'data_warehouse_person_property' },
                                                message: 'must be equal to constant',
                                            },
                                        ]
                                        return false
                                    }
                                    var valid0 = _errs9 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.value !== undefined) {
                                        const _errs11 = errors
                                        if (
                                            !validate13(data.value, {
                                                instancePath: instancePath + '/value',
                                                parentData: data,
                                                parentDataProperty: 'value',
                                                rootData,
                                            })
                                        ) {
                                            vErrors =
                                                vErrors === null ? validate13.errors : vErrors.concat(validate13.errors)
                                            errors = vErrors.length
                                        }
                                        var valid0 = _errs11 === errors
                                    } else {
                                        var valid0 = true
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } else {
            validate48.errors = [
                {
                    instancePath,
                    schemaPath: '#/type',
                    keyword: 'type',
                    params: { type: 'object' },
                    message: 'must be object',
                },
            ]
            return false
        }
    }
    validate48.errors = vErrors
    return errors === 0
}
const schema44 = {
    additionalProperties: false,
    properties: {
        key: { type: 'string' },
        label: { type: 'string' },
        operator: { $ref: '#/definitions/PropertyOperator' },
        type: { const: 'error_tracking_issue', type: 'string' },
        value: { $ref: '#/definitions/PropertyFilterValue' },
    },
    required: ['key', 'operator', 'type'],
    type: 'object',
}
function validate51(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if (
                (data.key === undefined && (missing0 = 'key')) ||
                (data.operator === undefined && (missing0 = 'operator')) ||
                (data.type === undefined && (missing0 = 'type'))
            ) {
                validate51.errors = [
                    {
                        instancePath,
                        schemaPath: '#/required',
                        keyword: 'required',
                        params: { missingProperty: missing0 },
                        message: "must have required property '" + missing0 + "'",
                    },
                ]
                return false
            } else {
                const _errs1 = errors
                for (const key0 in data) {
                    if (
                        !(
                            key0 === 'key' ||
                            key0 === 'label' ||
                            key0 === 'operator' ||
                            key0 === 'type' ||
                            key0 === 'value'
                        )
                    ) {
                        validate51.errors = [
                            {
                                instancePath,
                                schemaPath: '#/additionalProperties',
                                keyword: 'additionalProperties',
                                params: { additionalProperty: key0 },
                                message: 'must NOT have additional properties',
                            },
                        ]
                        return false
                        break
                    }
                }
                if (_errs1 === errors) {
                    if (data.key !== undefined) {
                        const _errs2 = errors
                        if (typeof data.key !== 'string') {
                            validate51.errors = [
                                {
                                    instancePath: instancePath + '/key',
                                    schemaPath: '#/properties/key/type',
                                    keyword: 'type',
                                    params: { type: 'string' },
                                    message: 'must be string',
                                },
                            ]
                            return false
                        }
                        var valid0 = _errs2 === errors
                    } else {
                        var valid0 = true
                    }
                    if (valid0) {
                        if (data.label !== undefined) {
                            const _errs4 = errors
                            if (typeof data.label !== 'string') {
                                validate51.errors = [
                                    {
                                        instancePath: instancePath + '/label',
                                        schemaPath: '#/properties/label/type',
                                        keyword: 'type',
                                        params: { type: 'string' },
                                        message: 'must be string',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs4 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.operator !== undefined) {
                                let data2 = data.operator
                                const _errs6 = errors
                                if (typeof data2 !== 'string') {
                                    validate51.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/type',
                                            keyword: 'type',
                                            params: { type: 'string' },
                                            message: 'must be string',
                                        },
                                    ]
                                    return false
                                }
                                if (
                                    !(
                                        data2 === 'exact' ||
                                        data2 === 'is_not' ||
                                        data2 === 'icontains' ||
                                        data2 === 'not_icontains' ||
                                        data2 === 'regex' ||
                                        data2 === 'not_regex' ||
                                        data2 === 'gt' ||
                                        data2 === 'gte' ||
                                        data2 === 'lt' ||
                                        data2 === 'lte' ||
                                        data2 === 'is_set' ||
                                        data2 === 'is_not_set' ||
                                        data2 === 'is_date_exact' ||
                                        data2 === 'is_date_before' ||
                                        data2 === 'is_date_after' ||
                                        data2 === 'between' ||
                                        data2 === 'not_between' ||
                                        data2 === 'min' ||
                                        data2 === 'max' ||
                                        data2 === 'in' ||
                                        data2 === 'not_in' ||
                                        data2 === 'is_cleaned_path_exact' ||
                                        data2 === 'flag_evaluates_to'
                                    )
                                ) {
                                    validate51.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/enum',
                                            keyword: 'enum',
                                            params: { allowedValues: schema14.enum },
                                            message: 'must be equal to one of the allowed values',
                                        },
                                    ]
                                    return false
                                }
                                var valid0 = _errs6 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.type !== undefined) {
                                    let data3 = data.type
                                    const _errs9 = errors
                                    if (typeof data3 !== 'string') {
                                        validate51.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/type',
                                                keyword: 'type',
                                                params: { type: 'string' },
                                                message: 'must be string',
                                            },
                                        ]
                                        return false
                                    }
                                    if ('error_tracking_issue' !== data3) {
                                        validate51.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/const',
                                                keyword: 'const',
                                                params: { allowedValue: 'error_tracking_issue' },
                                                message: 'must be equal to constant',
                                            },
                                        ]
                                        return false
                                    }
                                    var valid0 = _errs9 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.value !== undefined) {
                                        const _errs11 = errors
                                        if (
                                            !validate13(data.value, {
                                                instancePath: instancePath + '/value',
                                                parentData: data,
                                                parentDataProperty: 'value',
                                                rootData,
                                            })
                                        ) {
                                            vErrors =
                                                vErrors === null ? validate13.errors : vErrors.concat(validate13.errors)
                                            errors = vErrors.length
                                        }
                                        var valid0 = _errs11 === errors
                                    } else {
                                        var valid0 = true
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } else {
            validate51.errors = [
                {
                    instancePath,
                    schemaPath: '#/type',
                    keyword: 'type',
                    params: { type: 'object' },
                    message: 'must be object',
                },
            ]
            return false
        }
    }
    validate51.errors = vErrors
    return errors === 0
}
const schema46 = {
    additionalProperties: false,
    properties: {
        key: { type: 'string' },
        label: { type: 'string' },
        operator: { $ref: '#/definitions/PropertyOperator' },
        type: { const: 'log', type: 'string' },
        value: { $ref: '#/definitions/PropertyFilterValue' },
    },
    required: ['key', 'operator', 'type'],
    type: 'object',
}
function validate54(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if (
                (data.key === undefined && (missing0 = 'key')) ||
                (data.operator === undefined && (missing0 = 'operator')) ||
                (data.type === undefined && (missing0 = 'type'))
            ) {
                validate54.errors = [
                    {
                        instancePath,
                        schemaPath: '#/required',
                        keyword: 'required',
                        params: { missingProperty: missing0 },
                        message: "must have required property '" + missing0 + "'",
                    },
                ]
                return false
            } else {
                const _errs1 = errors
                for (const key0 in data) {
                    if (
                        !(
                            key0 === 'key' ||
                            key0 === 'label' ||
                            key0 === 'operator' ||
                            key0 === 'type' ||
                            key0 === 'value'
                        )
                    ) {
                        validate54.errors = [
                            {
                                instancePath,
                                schemaPath: '#/additionalProperties',
                                keyword: 'additionalProperties',
                                params: { additionalProperty: key0 },
                                message: 'must NOT have additional properties',
                            },
                        ]
                        return false
                        break
                    }
                }
                if (_errs1 === errors) {
                    if (data.key !== undefined) {
                        const _errs2 = errors
                        if (typeof data.key !== 'string') {
                            validate54.errors = [
                                {
                                    instancePath: instancePath + '/key',
                                    schemaPath: '#/properties/key/type',
                                    keyword: 'type',
                                    params: { type: 'string' },
                                    message: 'must be string',
                                },
                            ]
                            return false
                        }
                        var valid0 = _errs2 === errors
                    } else {
                        var valid0 = true
                    }
                    if (valid0) {
                        if (data.label !== undefined) {
                            const _errs4 = errors
                            if (typeof data.label !== 'string') {
                                validate54.errors = [
                                    {
                                        instancePath: instancePath + '/label',
                                        schemaPath: '#/properties/label/type',
                                        keyword: 'type',
                                        params: { type: 'string' },
                                        message: 'must be string',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs4 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.operator !== undefined) {
                                let data2 = data.operator
                                const _errs6 = errors
                                if (typeof data2 !== 'string') {
                                    validate54.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/type',
                                            keyword: 'type',
                                            params: { type: 'string' },
                                            message: 'must be string',
                                        },
                                    ]
                                    return false
                                }
                                if (
                                    !(
                                        data2 === 'exact' ||
                                        data2 === 'is_not' ||
                                        data2 === 'icontains' ||
                                        data2 === 'not_icontains' ||
                                        data2 === 'regex' ||
                                        data2 === 'not_regex' ||
                                        data2 === 'gt' ||
                                        data2 === 'gte' ||
                                        data2 === 'lt' ||
                                        data2 === 'lte' ||
                                        data2 === 'is_set' ||
                                        data2 === 'is_not_set' ||
                                        data2 === 'is_date_exact' ||
                                        data2 === 'is_date_before' ||
                                        data2 === 'is_date_after' ||
                                        data2 === 'between' ||
                                        data2 === 'not_between' ||
                                        data2 === 'min' ||
                                        data2 === 'max' ||
                                        data2 === 'in' ||
                                        data2 === 'not_in' ||
                                        data2 === 'is_cleaned_path_exact' ||
                                        data2 === 'flag_evaluates_to'
                                    )
                                ) {
                                    validate54.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/enum',
                                            keyword: 'enum',
                                            params: { allowedValues: schema14.enum },
                                            message: 'must be equal to one of the allowed values',
                                        },
                                    ]
                                    return false
                                }
                                var valid0 = _errs6 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.type !== undefined) {
                                    let data3 = data.type
                                    const _errs9 = errors
                                    if (typeof data3 !== 'string') {
                                        validate54.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/type',
                                                keyword: 'type',
                                                params: { type: 'string' },
                                                message: 'must be string',
                                            },
                                        ]
                                        return false
                                    }
                                    if ('log' !== data3) {
                                        validate54.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/const',
                                                keyword: 'const',
                                                params: { allowedValue: 'log' },
                                                message: 'must be equal to constant',
                                            },
                                        ]
                                        return false
                                    }
                                    var valid0 = _errs9 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.value !== undefined) {
                                        const _errs11 = errors
                                        if (
                                            !validate13(data.value, {
                                                instancePath: instancePath + '/value',
                                                parentData: data,
                                                parentDataProperty: 'value',
                                                rootData,
                                            })
                                        ) {
                                            vErrors =
                                                vErrors === null ? validate13.errors : vErrors.concat(validate13.errors)
                                            errors = vErrors.length
                                        }
                                        var valid0 = _errs11 === errors
                                    } else {
                                        var valid0 = true
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } else {
            validate54.errors = [
                {
                    instancePath,
                    schemaPath: '#/type',
                    keyword: 'type',
                    params: { type: 'object' },
                    message: 'must be object',
                },
            ]
            return false
        }
    }
    validate54.errors = vErrors
    return errors === 0
}
const schema48 = {
    additionalProperties: false,
    properties: {
        key: { type: 'string' },
        label: { type: 'string' },
        operator: { $ref: '#/definitions/PropertyOperator' },
        type: { const: 'revenue_analytics', type: 'string' },
        value: { $ref: '#/definitions/PropertyFilterValue' },
    },
    required: ['key', 'operator', 'type'],
    type: 'object',
}
function validate57(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if (
                (data.key === undefined && (missing0 = 'key')) ||
                (data.operator === undefined && (missing0 = 'operator')) ||
                (data.type === undefined && (missing0 = 'type'))
            ) {
                validate57.errors = [
                    {
                        instancePath,
                        schemaPath: '#/required',
                        keyword: 'required',
                        params: { missingProperty: missing0 },
                        message: "must have required property '" + missing0 + "'",
                    },
                ]
                return false
            } else {
                const _errs1 = errors
                for (const key0 in data) {
                    if (
                        !(
                            key0 === 'key' ||
                            key0 === 'label' ||
                            key0 === 'operator' ||
                            key0 === 'type' ||
                            key0 === 'value'
                        )
                    ) {
                        validate57.errors = [
                            {
                                instancePath,
                                schemaPath: '#/additionalProperties',
                                keyword: 'additionalProperties',
                                params: { additionalProperty: key0 },
                                message: 'must NOT have additional properties',
                            },
                        ]
                        return false
                        break
                    }
                }
                if (_errs1 === errors) {
                    if (data.key !== undefined) {
                        const _errs2 = errors
                        if (typeof data.key !== 'string') {
                            validate57.errors = [
                                {
                                    instancePath: instancePath + '/key',
                                    schemaPath: '#/properties/key/type',
                                    keyword: 'type',
                                    params: { type: 'string' },
                                    message: 'must be string',
                                },
                            ]
                            return false
                        }
                        var valid0 = _errs2 === errors
                    } else {
                        var valid0 = true
                    }
                    if (valid0) {
                        if (data.label !== undefined) {
                            const _errs4 = errors
                            if (typeof data.label !== 'string') {
                                validate57.errors = [
                                    {
                                        instancePath: instancePath + '/label',
                                        schemaPath: '#/properties/label/type',
                                        keyword: 'type',
                                        params: { type: 'string' },
                                        message: 'must be string',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs4 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.operator !== undefined) {
                                let data2 = data.operator
                                const _errs6 = errors
                                if (typeof data2 !== 'string') {
                                    validate57.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/type',
                                            keyword: 'type',
                                            params: { type: 'string' },
                                            message: 'must be string',
                                        },
                                    ]
                                    return false
                                }
                                if (
                                    !(
                                        data2 === 'exact' ||
                                        data2 === 'is_not' ||
                                        data2 === 'icontains' ||
                                        data2 === 'not_icontains' ||
                                        data2 === 'regex' ||
                                        data2 === 'not_regex' ||
                                        data2 === 'gt' ||
                                        data2 === 'gte' ||
                                        data2 === 'lt' ||
                                        data2 === 'lte' ||
                                        data2 === 'is_set' ||
                                        data2 === 'is_not_set' ||
                                        data2 === 'is_date_exact' ||
                                        data2 === 'is_date_before' ||
                                        data2 === 'is_date_after' ||
                                        data2 === 'between' ||
                                        data2 === 'not_between' ||
                                        data2 === 'min' ||
                                        data2 === 'max' ||
                                        data2 === 'in' ||
                                        data2 === 'not_in' ||
                                        data2 === 'is_cleaned_path_exact' ||
                                        data2 === 'flag_evaluates_to'
                                    )
                                ) {
                                    validate57.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/enum',
                                            keyword: 'enum',
                                            params: { allowedValues: schema14.enum },
                                            message: 'must be equal to one of the allowed values',
                                        },
                                    ]
                                    return false
                                }
                                var valid0 = _errs6 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.type !== undefined) {
                                    let data3 = data.type
                                    const _errs9 = errors
                                    if (typeof data3 !== 'string') {
                                        validate57.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/type',
                                                keyword: 'type',
                                                params: { type: 'string' },
                                                message: 'must be string',
                                            },
                                        ]
                                        return false
                                    }
                                    if ('revenue_analytics' !== data3) {
                                        validate57.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/const',
                                                keyword: 'const',
                                                params: { allowedValue: 'revenue_analytics' },
                                                message: 'must be equal to constant',
                                            },
                                        ]
                                        return false
                                    }
                                    var valid0 = _errs9 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.value !== undefined) {
                                        const _errs11 = errors
                                        if (
                                            !validate13(data.value, {
                                                instancePath: instancePath + '/value',
                                                parentData: data,
                                                parentDataProperty: 'value',
                                                rootData,
                                            })
                                        ) {
                                            vErrors =
                                                vErrors === null ? validate13.errors : vErrors.concat(validate13.errors)
                                            errors = vErrors.length
                                        }
                                        var valid0 = _errs11 === errors
                                    } else {
                                        var valid0 = true
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } else {
            validate57.errors = [
                {
                    instancePath,
                    schemaPath: '#/type',
                    keyword: 'type',
                    params: { type: 'object' },
                    message: 'must be object',
                },
            ]
            return false
        }
    }
    validate57.errors = vErrors
    return errors === 0
}
function validate11(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    const _errs0 = errors
    let valid0 = false
    const _errs1 = errors
    if (!validate12(data, { instancePath, parentData, parentDataProperty, rootData })) {
        vErrors = vErrors === null ? validate12.errors : vErrors.concat(validate12.errors)
        errors = vErrors.length
    }
    var _valid0 = _errs1 === errors
    valid0 = valid0 || _valid0
    if (!valid0) {
        const _errs2 = errors
        if (!validate16(data, { instancePath, parentData, parentDataProperty, rootData })) {
            vErrors = vErrors === null ? validate16.errors : vErrors.concat(validate16.errors)
            errors = vErrors.length
        }
        var _valid0 = _errs2 === errors
        valid0 = valid0 || _valid0
        if (!valid0) {
            const _errs3 = errors
            if (!validate19(data, { instancePath, parentData, parentDataProperty, rootData })) {
                vErrors = vErrors === null ? validate19.errors : vErrors.concat(validate19.errors)
                errors = vErrors.length
            }
            var _valid0 = _errs3 === errors
            valid0 = valid0 || _valid0
            if (!valid0) {
                const _errs4 = errors
                if (!validate22(data, { instancePath, parentData, parentDataProperty, rootData })) {
                    vErrors = vErrors === null ? validate22.errors : vErrors.concat(validate22.errors)
                    errors = vErrors.length
                }
                var _valid0 = _errs4 === errors
                valid0 = valid0 || _valid0
                if (!valid0) {
                    const _errs5 = errors
                    if (!validate25(data, { instancePath, parentData, parentDataProperty, rootData })) {
                        vErrors = vErrors === null ? validate25.errors : vErrors.concat(validate25.errors)
                        errors = vErrors.length
                    }
                    var _valid0 = _errs5 === errors
                    valid0 = valid0 || _valid0
                    if (!valid0) {
                        const _errs6 = errors
                        if (!validate28(data, { instancePath, parentData, parentDataProperty, rootData })) {
                            vErrors = vErrors === null ? validate28.errors : vErrors.concat(validate28.errors)
                            errors = vErrors.length
                        }
                        var _valid0 = _errs6 === errors
                        valid0 = valid0 || _valid0
                        if (!valid0) {
                            const _errs7 = errors
                            if (!validate30(data, { instancePath, parentData, parentDataProperty, rootData })) {
                                vErrors = vErrors === null ? validate30.errors : vErrors.concat(validate30.errors)
                                errors = vErrors.length
                            }
                            var _valid0 = _errs7 === errors
                            valid0 = valid0 || _valid0
                            if (!valid0) {
                                const _errs8 = errors
                                if (!validate33(data, { instancePath, parentData, parentDataProperty, rootData })) {
                                    vErrors = vErrors === null ? validate33.errors : vErrors.concat(validate33.errors)
                                    errors = vErrors.length
                                }
                                var _valid0 = _errs8 === errors
                                valid0 = valid0 || _valid0
                                if (!valid0) {
                                    const _errs9 = errors
                                    if (!validate36(data, { instancePath, parentData, parentDataProperty, rootData })) {
                                        vErrors =
                                            vErrors === null ? validate36.errors : vErrors.concat(validate36.errors)
                                        errors = vErrors.length
                                    }
                                    var _valid0 = _errs9 === errors
                                    valid0 = valid0 || _valid0
                                    if (!valid0) {
                                        const _errs10 = errors
                                        if (
                                            !validate39(data, {
                                                instancePath,
                                                parentData,
                                                parentDataProperty,
                                                rootData,
                                            })
                                        ) {
                                            vErrors =
                                                vErrors === null ? validate39.errors : vErrors.concat(validate39.errors)
                                            errors = vErrors.length
                                        }
                                        var _valid0 = _errs10 === errors
                                        valid0 = valid0 || _valid0
                                        if (!valid0) {
                                            const _errs11 = errors
                                            const _errs12 = errors
                                            if (errors === _errs12) {
                                                if (data && typeof data == 'object' && !Array.isArray(data)) {
                                                    let missing0
                                                    if (
                                                        (data.key === undefined && (missing0 = 'key')) ||
                                                        (data.operator === undefined && (missing0 = 'operator')) ||
                                                        (data.type === undefined && (missing0 = 'type')) ||
                                                        (data.value === undefined && (missing0 = 'value'))
                                                    ) {
                                                        const err0 = {
                                                            instancePath,
                                                            schemaPath: '#/definitions/FlagPropertyFilter/required',
                                                            keyword: 'required',
                                                            params: { missingProperty: missing0 },
                                                            message: "must have required property '" + missing0 + "'",
                                                        }
                                                        if (vErrors === null) {
                                                            vErrors = [err0]
                                                        } else {
                                                            vErrors.push(err0)
                                                        }
                                                        errors++
                                                    } else {
                                                        const _errs14 = errors
                                                        for (const key0 in data) {
                                                            if (
                                                                !(
                                                                    key0 === 'key' ||
                                                                    key0 === 'label' ||
                                                                    key0 === 'operator' ||
                                                                    key0 === 'type' ||
                                                                    key0 === 'value'
                                                                )
                                                            ) {
                                                                const err1 = {
                                                                    instancePath,
                                                                    schemaPath:
                                                                        '#/definitions/FlagPropertyFilter/additionalProperties',
                                                                    keyword: 'additionalProperties',
                                                                    params: { additionalProperty: key0 },
                                                                    message: 'must NOT have additional properties',
                                                                }
                                                                if (vErrors === null) {
                                                                    vErrors = [err1]
                                                                } else {
                                                                    vErrors.push(err1)
                                                                }
                                                                errors++
                                                                break
                                                            }
                                                        }
                                                        if (_errs14 === errors) {
                                                            if (data.key !== undefined) {
                                                                const _errs15 = errors
                                                                if (typeof data.key !== 'string') {
                                                                    const err2 = {
                                                                        instancePath: instancePath + '/key',
                                                                        schemaPath:
                                                                            '#/definitions/FlagPropertyFilter/properties/key/type',
                                                                        keyword: 'type',
                                                                        params: { type: 'string' },
                                                                        message: 'must be string',
                                                                    }
                                                                    if (vErrors === null) {
                                                                        vErrors = [err2]
                                                                    } else {
                                                                        vErrors.push(err2)
                                                                    }
                                                                    errors++
                                                                }
                                                                var valid2 = _errs15 === errors
                                                            } else {
                                                                var valid2 = true
                                                            }
                                                            if (valid2) {
                                                                if (data.label !== undefined) {
                                                                    const _errs17 = errors
                                                                    if (typeof data.label !== 'string') {
                                                                        const err3 = {
                                                                            instancePath: instancePath + '/label',
                                                                            schemaPath:
                                                                                '#/definitions/FlagPropertyFilter/properties/label/type',
                                                                            keyword: 'type',
                                                                            params: { type: 'string' },
                                                                            message: 'must be string',
                                                                        }
                                                                        if (vErrors === null) {
                                                                            vErrors = [err3]
                                                                        } else {
                                                                            vErrors.push(err3)
                                                                        }
                                                                        errors++
                                                                    }
                                                                    var valid2 = _errs17 === errors
                                                                } else {
                                                                    var valid2 = true
                                                                }
                                                                if (valid2) {
                                                                    if (data.operator !== undefined) {
                                                                        let data2 = data.operator
                                                                        const _errs19 = errors
                                                                        if (typeof data2 !== 'string') {
                                                                            const err4 = {
                                                                                instancePath:
                                                                                    instancePath + '/operator',
                                                                                schemaPath:
                                                                                    '#/definitions/FlagPropertyFilter/properties/operator/type',
                                                                                keyword: 'type',
                                                                                params: { type: 'string' },
                                                                                message: 'must be string',
                                                                            }
                                                                            if (vErrors === null) {
                                                                                vErrors = [err4]
                                                                            } else {
                                                                                vErrors.push(err4)
                                                                            }
                                                                            errors++
                                                                        }
                                                                        if ('flag_evaluates_to' !== data2) {
                                                                            const err5 = {
                                                                                instancePath:
                                                                                    instancePath + '/operator',
                                                                                schemaPath:
                                                                                    '#/definitions/FlagPropertyFilter/properties/operator/const',
                                                                                keyword: 'const',
                                                                                params: {
                                                                                    allowedValue: 'flag_evaluates_to',
                                                                                },
                                                                                message: 'must be equal to constant',
                                                                            }
                                                                            if (vErrors === null) {
                                                                                vErrors = [err5]
                                                                            } else {
                                                                                vErrors.push(err5)
                                                                            }
                                                                            errors++
                                                                        }
                                                                        var valid2 = _errs19 === errors
                                                                    } else {
                                                                        var valid2 = true
                                                                    }
                                                                    if (valid2) {
                                                                        if (data.type !== undefined) {
                                                                            let data3 = data.type
                                                                            const _errs21 = errors
                                                                            if (typeof data3 !== 'string') {
                                                                                const err6 = {
                                                                                    instancePath:
                                                                                        instancePath + '/type',
                                                                                    schemaPath:
                                                                                        '#/definitions/FlagPropertyFilter/properties/type/type',
                                                                                    keyword: 'type',
                                                                                    params: { type: 'string' },
                                                                                    message: 'must be string',
                                                                                }
                                                                                if (vErrors === null) {
                                                                                    vErrors = [err6]
                                                                                } else {
                                                                                    vErrors.push(err6)
                                                                                }
                                                                                errors++
                                                                            }
                                                                            if ('flag' !== data3) {
                                                                                const err7 = {
                                                                                    instancePath:
                                                                                        instancePath + '/type',
                                                                                    schemaPath:
                                                                                        '#/definitions/FlagPropertyFilter/properties/type/const',
                                                                                    keyword: 'const',
                                                                                    params: { allowedValue: 'flag' },
                                                                                    message:
                                                                                        'must be equal to constant',
                                                                                }
                                                                                if (vErrors === null) {
                                                                                    vErrors = [err7]
                                                                                } else {
                                                                                    vErrors.push(err7)
                                                                                }
                                                                                errors++
                                                                            }
                                                                            var valid2 = _errs21 === errors
                                                                        } else {
                                                                            var valid2 = true
                                                                        }
                                                                        if (valid2) {
                                                                            if (data.value !== undefined) {
                                                                                let data4 = data.value
                                                                                const _errs23 = errors
                                                                                if (
                                                                                    typeof data4 !== 'boolean' &&
                                                                                    typeof data4 !== 'string'
                                                                                ) {
                                                                                    const err8 = {
                                                                                        instancePath:
                                                                                            instancePath + '/value',
                                                                                        schemaPath:
                                                                                            '#/definitions/FlagPropertyFilter/properties/value/type',
                                                                                        keyword: 'type',
                                                                                        params: {
                                                                                            type: schema37.properties
                                                                                                .value.type,
                                                                                        },
                                                                                        message:
                                                                                            'must be boolean,string',
                                                                                    }
                                                                                    if (vErrors === null) {
                                                                                        vErrors = [err8]
                                                                                    } else {
                                                                                        vErrors.push(err8)
                                                                                    }
                                                                                    errors++
                                                                                }
                                                                                var valid2 = _errs23 === errors
                                                                            } else {
                                                                                var valid2 = true
                                                                            }
                                                                        }
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                } else {
                                                    const err9 = {
                                                        instancePath,
                                                        schemaPath: '#/definitions/FlagPropertyFilter/type',
                                                        keyword: 'type',
                                                        params: { type: 'object' },
                                                        message: 'must be object',
                                                    }
                                                    if (vErrors === null) {
                                                        vErrors = [err9]
                                                    } else {
                                                        vErrors.push(err9)
                                                    }
                                                    errors++
                                                }
                                            }
                                            var _valid0 = _errs11 === errors
                                            valid0 = valid0 || _valid0
                                            if (!valid0) {
                                                const _errs25 = errors
                                                if (
                                                    !validate42(data, {
                                                        instancePath,
                                                        parentData,
                                                        parentDataProperty,
                                                        rootData,
                                                    })
                                                ) {
                                                    vErrors =
                                                        vErrors === null
                                                            ? validate42.errors
                                                            : vErrors.concat(validate42.errors)
                                                    errors = vErrors.length
                                                }
                                                var _valid0 = _errs25 === errors
                                                valid0 = valid0 || _valid0
                                                if (!valid0) {
                                                    const _errs26 = errors
                                                    const _errs27 = errors
                                                    if (errors === _errs27) {
                                                        if (data && typeof data == 'object' && !Array.isArray(data)) {
                                                            for (const key1 in data) {
                                                                const err10 = {
                                                                    instancePath,
                                                                    schemaPath:
                                                                        '#/definitions/EmptyPropertyFilter/additionalProperties',
                                                                    keyword: 'additionalProperties',
                                                                    params: { additionalProperty: key1 },
                                                                    message: 'must NOT have additional properties',
                                                                }
                                                                if (vErrors === null) {
                                                                    vErrors = [err10]
                                                                } else {
                                                                    vErrors.push(err10)
                                                                }
                                                                errors++
                                                                break
                                                            }
                                                        } else {
                                                            const err11 = {
                                                                instancePath,
                                                                schemaPath: '#/definitions/EmptyPropertyFilter/type',
                                                                keyword: 'type',
                                                                params: { type: 'object' },
                                                                message: 'must be object',
                                                            }
                                                            if (vErrors === null) {
                                                                vErrors = [err11]
                                                            } else {
                                                                vErrors.push(err11)
                                                            }
                                                            errors++
                                                        }
                                                    }
                                                    var _valid0 = _errs26 === errors
                                                    valid0 = valid0 || _valid0
                                                    if (!valid0) {
                                                        const _errs30 = errors
                                                        if (
                                                            !validate45(data, {
                                                                instancePath,
                                                                parentData,
                                                                parentDataProperty,
                                                                rootData,
                                                            })
                                                        ) {
                                                            vErrors =
                                                                vErrors === null
                                                                    ? validate45.errors
                                                                    : vErrors.concat(validate45.errors)
                                                            errors = vErrors.length
                                                        }
                                                        var _valid0 = _errs30 === errors
                                                        valid0 = valid0 || _valid0
                                                        if (!valid0) {
                                                            const _errs31 = errors
                                                            if (
                                                                !validate48(data, {
                                                                    instancePath,
                                                                    parentData,
                                                                    parentDataProperty,
                                                                    rootData,
                                                                })
                                                            ) {
                                                                vErrors =
                                                                    vErrors === null
                                                                        ? validate48.errors
                                                                        : vErrors.concat(validate48.errors)
                                                                errors = vErrors.length
                                                            }
                                                            var _valid0 = _errs31 === errors
                                                            valid0 = valid0 || _valid0
                                                            if (!valid0) {
                                                                const _errs32 = errors
                                                                if (
                                                                    !validate51(data, {
                                                                        instancePath,
                                                                        parentData,
                                                                        parentDataProperty,
                                                                        rootData,
                                                                    })
                                                                ) {
                                                                    vErrors =
                                                                        vErrors === null
                                                                            ? validate51.errors
                                                                            : vErrors.concat(validate51.errors)
                                                                    errors = vErrors.length
                                                                }
                                                                var _valid0 = _errs32 === errors
                                                                valid0 = valid0 || _valid0
                                                                if (!valid0) {
                                                                    const _errs33 = errors
                                                                    if (
                                                                        !validate54(data, {
                                                                            instancePath,
                                                                            parentData,
                                                                            parentDataProperty,
                                                                            rootData,
                                                                        })
                                                                    ) {
                                                                        vErrors =
                                                                            vErrors === null
                                                                                ? validate54.errors
                                                                                : vErrors.concat(validate54.errors)
                                                                        errors = vErrors.length
                                                                    }
                                                                    var _valid0 = _errs33 === errors
                                                                    valid0 = valid0 || _valid0
                                                                    if (!valid0) {
                                                                        const _errs34 = errors
                                                                        if (
                                                                            !validate57(data, {
                                                                                instancePath,
                                                                                parentData,
                                                                                parentDataProperty,
                                                                                rootData,
                                                                            })
                                                                        ) {
                                                                            vErrors =
                                                                                vErrors === null
                                                                                    ? validate57.errors
                                                                                    : vErrors.concat(validate57.errors)
                                                                            errors = vErrors.length
                                                                        }
                                                                        var _valid0 = _errs34 === errors
                                                                        valid0 = valid0 || _valid0
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    if (!valid0) {
        const err12 = {
            instancePath,
            schemaPath: '#/anyOf',
            keyword: 'anyOf',
            params: {},
            message: 'must match a schema in anyOf',
        }
        if (vErrors === null) {
            vErrors = [err12]
        } else {
            vErrors.push(err12)
        }
        errors++
        validate11.errors = vErrors
        return false
    } else {
        errors = _errs0
        if (vErrors !== null) {
            if (_errs0) {
                vErrors.length = _errs0
            } else {
                vErrors = null
            }
        }
    }
    validate11.errors = vErrors
    return errors === 0
}
export const WebAnalyticsPropertyFilters = validate60
const schema50 = { items: { $ref: '#/definitions/WebAnalyticsPropertyFilter' }, type: 'array' }
const schema51 = {
    anyOf: [
        { $ref: '#/definitions/EventPropertyFilter' },
        { $ref: '#/definitions/PersonPropertyFilter' },
        { $ref: '#/definitions/SessionPropertyFilter' },
    ],
}
function validate61(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    const _errs0 = errors
    let valid0 = false
    const _errs1 = errors
    if (!validate12(data, { instancePath, parentData, parentDataProperty, rootData })) {
        vErrors = vErrors === null ? validate12.errors : vErrors.concat(validate12.errors)
        errors = vErrors.length
    }
    var _valid0 = _errs1 === errors
    valid0 = valid0 || _valid0
    if (!valid0) {
        const _errs2 = errors
        if (!validate16(data, { instancePath, parentData, parentDataProperty, rootData })) {
            vErrors = vErrors === null ? validate16.errors : vErrors.concat(validate16.errors)
            errors = vErrors.length
        }
        var _valid0 = _errs2 === errors
        valid0 = valid0 || _valid0
        if (!valid0) {
            const _errs3 = errors
            if (!validate25(data, { instancePath, parentData, parentDataProperty, rootData })) {
                vErrors = vErrors === null ? validate25.errors : vErrors.concat(validate25.errors)
                errors = vErrors.length
            }
            var _valid0 = _errs3 === errors
            valid0 = valid0 || _valid0
        }
    }
    if (!valid0) {
        const err0 = {
            instancePath,
            schemaPath: '#/anyOf',
            keyword: 'anyOf',
            params: {},
            message: 'must match a schema in anyOf',
        }
        if (vErrors === null) {
            vErrors = [err0]
        } else {
            vErrors.push(err0)
        }
        errors++
        validate61.errors = vErrors
        return false
    } else {
        errors = _errs0
        if (vErrors !== null) {
            if (_errs0) {
                vErrors.length = _errs0
            } else {
                vErrors = null
            }
        }
    }
    validate61.errors = vErrors
    return errors === 0
}
function validate60(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (Array.isArray(data)) {
            var valid0 = true
            const len0 = data.length
            for (let i0 = 0; i0 < len0; i0++) {
                const _errs1 = errors
                if (
                    !validate61(data[i0], {
                        instancePath: instancePath + '/' + i0,
                        parentData: data,
                        parentDataProperty: i0,
                        rootData,
                    })
                ) {
                    vErrors = vErrors === null ? validate61.errors : vErrors.concat(validate61.errors)
                    errors = vErrors.length
                }
                var valid0 = _errs1 === errors
                if (!valid0) {
                    break
                }
            }
        } else {
            validate60.errors = [
                {
                    instancePath,
                    schemaPath: '#/type',
                    keyword: 'type',
                    params: { type: 'array' },
                    message: 'must be array',
                },
            ]
            return false
        }
    }
    validate60.errors = vErrors
    return errors === 0
}
export const RevenueAnalyticsPropertyFilters = validate66
const schema52 = { items: { $ref: '#/definitions/RevenueAnalyticsPropertyFilter' }, type: 'array' }
function validate66(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (Array.isArray(data)) {
            var valid0 = true
            const len0 = data.length
            for (let i0 = 0; i0 < len0; i0++) {
                const _errs1 = errors
                if (
                    !validate57(data[i0], {
                        instancePath: instancePath + '/' + i0,
                        parentData: data,
                        parentDataProperty: i0,
                        rootData,
                    })
                ) {
                    vErrors = vErrors === null ? validate57.errors : vErrors.concat(validate57.errors)
                    errors = vErrors.length
                }
                var valid0 = _errs1 === errors
                if (!valid0) {
                    break
                }
            }
        } else {
            validate66.errors = [
                {
                    instancePath,
                    schemaPath: '#/type',
                    keyword: 'type',
                    params: { type: 'array' },
                    message: 'must be array',
                },
            ]
            return false
        }
    }
    validate66.errors = vErrors
    return errors === 0
}
export const SessionPropertyFilter = validate68
function validate68(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if (
                (data.key === undefined && (missing0 = 'key')) ||
                (data.operator === undefined && (missing0 = 'operator')) ||
                (data.type === undefined && (missing0 = 'type'))
            ) {
                validate68.errors = [
                    {
                        instancePath,
                        schemaPath: '#/required',
                        keyword: 'required',
                        params: { missingProperty: missing0 },
                        message: "must have required property '" + missing0 + "'",
                    },
                ]
                return false
            } else {
                const _errs1 = errors
                for (const key0 in data) {
                    if (
                        !(
                            key0 === 'key' ||
                            key0 === 'label' ||
                            key0 === 'operator' ||
                            key0 === 'type' ||
                            key0 === 'value'
                        )
                    ) {
                        validate68.errors = [
                            {
                                instancePath,
                                schemaPath: '#/additionalProperties',
                                keyword: 'additionalProperties',
                                params: { additionalProperty: key0 },
                                message: 'must NOT have additional properties',
                            },
                        ]
                        return false
                        break
                    }
                }
                if (_errs1 === errors) {
                    if (data.key !== undefined) {
                        const _errs2 = errors
                        if (typeof data.key !== 'string') {
                            validate68.errors = [
                                {
                                    instancePath: instancePath + '/key',
                                    schemaPath: '#/properties/key/type',
                                    keyword: 'type',
                                    params: { type: 'string' },
                                    message: 'must be string',
                                },
                            ]
                            return false
                        }
                        var valid0 = _errs2 === errors
                    } else {
                        var valid0 = true
                    }
                    if (valid0) {
                        if (data.label !== undefined) {
                            const _errs4 = errors
                            if (typeof data.label !== 'string') {
                                validate68.errors = [
                                    {
                                        instancePath: instancePath + '/label',
                                        schemaPath: '#/properties/label/type',
                                        keyword: 'type',
                                        params: { type: 'string' },
                                        message: 'must be string',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs4 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.operator !== undefined) {
                                let data2 = data.operator
                                const _errs6 = errors
                                if (typeof data2 !== 'string') {
                                    validate68.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/type',
                                            keyword: 'type',
                                            params: { type: 'string' },
                                            message: 'must be string',
                                        },
                                    ]
                                    return false
                                }
                                if (
                                    !(
                                        data2 === 'exact' ||
                                        data2 === 'is_not' ||
                                        data2 === 'icontains' ||
                                        data2 === 'not_icontains' ||
                                        data2 === 'regex' ||
                                        data2 === 'not_regex' ||
                                        data2 === 'gt' ||
                                        data2 === 'gte' ||
                                        data2 === 'lt' ||
                                        data2 === 'lte' ||
                                        data2 === 'is_set' ||
                                        data2 === 'is_not_set' ||
                                        data2 === 'is_date_exact' ||
                                        data2 === 'is_date_before' ||
                                        data2 === 'is_date_after' ||
                                        data2 === 'between' ||
                                        data2 === 'not_between' ||
                                        data2 === 'min' ||
                                        data2 === 'max' ||
                                        data2 === 'in' ||
                                        data2 === 'not_in' ||
                                        data2 === 'is_cleaned_path_exact' ||
                                        data2 === 'flag_evaluates_to'
                                    )
                                ) {
                                    validate68.errors = [
                                        {
                                            instancePath: instancePath + '/operator',
                                            schemaPath: '#/definitions/PropertyOperator/enum',
                                            keyword: 'enum',
                                            params: { allowedValues: schema14.enum },
                                            message: 'must be equal to one of the allowed values',
                                        },
                                    ]
                                    return false
                                }
                                var valid0 = _errs6 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.type !== undefined) {
                                    let data3 = data.type
                                    const _errs9 = errors
                                    if (typeof data3 !== 'string') {
                                        validate68.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/type',
                                                keyword: 'type',
                                                params: { type: 'string' },
                                                message: 'must be string',
                                            },
                                        ]
                                        return false
                                    }
                                    if ('session' !== data3) {
                                        validate68.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/const',
                                                keyword: 'const',
                                                params: { allowedValue: 'session' },
                                                message: 'must be equal to constant',
                                            },
                                        ]
                                        return false
                                    }
                                    var valid0 = _errs9 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.value !== undefined) {
                                        const _errs11 = errors
                                        if (
                                            !validate13(data.value, {
                                                instancePath: instancePath + '/value',
                                                parentData: data,
                                                parentDataProperty: 'value',
                                                rootData,
                                            })
                                        ) {
                                            vErrors =
                                                vErrors === null ? validate13.errors : vErrors.concat(validate13.errors)
                                            errors = vErrors.length
                                        }
                                        var valid0 = _errs11 === errors
                                    } else {
                                        var valid0 = true
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } else {
            validate68.errors = [
                {
                    instancePath,
                    schemaPath: '#/type',
                    keyword: 'type',
                    params: { type: 'object' },
                    message: 'must be object',
                },
            ]
            return false
        }
    }
    validate68.errors = vErrors
    return errors === 0
}
export const CompareFilter = validate70
const schema55 = {
    additionalProperties: false,
    properties: {
        compare: {
            default: false,
            description: 'Whether to compare the current date range to a previous date range.',
            type: 'boolean',
        },
        compare_to: {
            description:
                'The date range to compare to. The value is a relative date. Examples of relative dates are: `-1y` for 1 year ago, `-14m` for 14 months ago, `-100w` for 100 weeks ago, `-14d` for 14 days ago, `-30h` for 30 hours ago.',
            type: 'string',
        },
    },
    type: 'object',
}
function validate70(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            const _errs1 = errors
            for (const key0 in data) {
                if (!(key0 === 'compare' || key0 === 'compare_to')) {
                    validate70.errors = [
                        {
                            instancePath,
                            schemaPath: '#/additionalProperties',
                            keyword: 'additionalProperties',
                            params: { additionalProperty: key0 },
                            message: 'must NOT have additional properties',
                        },
                    ]
                    return false
                    break
                }
            }
            if (_errs1 === errors) {
                if (data.compare !== undefined) {
                    const _errs2 = errors
                    if (typeof data.compare !== 'boolean') {
                        validate70.errors = [
                            {
                                instancePath: instancePath + '/compare',
                                schemaPath: '#/properties/compare/type',
                                keyword: 'type',
                                params: { type: 'boolean' },
                                message: 'must be boolean',
                            },
                        ]
                        return false
                    }
                    var valid0 = _errs2 === errors
                } else {
                    var valid0 = true
                }
                if (valid0) {
                    if (data.compare_to !== undefined) {
                        const _errs4 = errors
                        if (typeof data.compare_to !== 'string') {
                            validate70.errors = [
                                {
                                    instancePath: instancePath + '/compare_to',
                                    schemaPath: '#/properties/compare_to/type',
                                    keyword: 'type',
                                    params: { type: 'string' },
                                    message: 'must be string',
                                },
                            ]
                            return false
                        }
                        var valid0 = _errs4 === errors
                    } else {
                        var valid0 = true
                    }
                }
            }
        } else {
            validate70.errors = [
                {
                    instancePath,
                    schemaPath: '#/type',
                    keyword: 'type',
                    params: { type: 'object' },
                    message: 'must be object',
                },
            ]
            return false
        }
    }
    validate70.errors = vErrors
    return errors === 0
}
