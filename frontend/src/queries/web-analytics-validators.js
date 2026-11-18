// AUTO-GENERATED FILE - DO NOT EDIT DIRECTLY
'use strict'
export const WebAnalyticsPropertyFilters = validate154
const schema136 = { items: { $ref: '#/definitions/WebAnalyticsPropertyFilter' }, type: 'array' }
const schema137 = {
    anyOf: [
        { $ref: '#/definitions/EventPropertyFilter' },
        { $ref: '#/definitions/PersonPropertyFilter' },
        { $ref: '#/definitions/SessionPropertyFilter' },
        { $ref: '#/definitions/CohortPropertyFilter' },
    ],
}
const schema13 = {
    additionalProperties: false,
    description: 'Sync with nodejs/src/types.ts',
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
    description: 'Sync with nodejs/src/types.ts',
    enum: [
        'exact',
        'is_not',
        'icontains',
        'not_icontains',
        'starts_with',
        'not_starts_with',
        'ends_with',
        'not_ends_with',
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
        'is_cleaned_path_not_exact',
        'flag_evaluates_to',
        'semver_eq',
        'semver_neq',
        'semver_gt',
        'semver_gte',
        'semver_lt',
        'semver_lte',
        'semver_tilde',
        'semver_caret',
        'semver_wildcard',
        'icontains_multi',
        'not_icontains_multi',
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
                                        data2 === 'starts_with' ||
                                        data2 === 'not_starts_with' ||
                                        data2 === 'ends_with' ||
                                        data2 === 'not_ends_with' ||
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
                                        data2 === 'is_cleaned_path_not_exact' ||
                                        data2 === 'flag_evaluates_to' ||
                                        data2 === 'semver_eq' ||
                                        data2 === 'semver_neq' ||
                                        data2 === 'semver_gt' ||
                                        data2 === 'semver_gte' ||
                                        data2 === 'semver_lt' ||
                                        data2 === 'semver_lte' ||
                                        data2 === 'semver_tilde' ||
                                        data2 === 'semver_caret' ||
                                        data2 === 'semver_wildcard' ||
                                        data2 === 'icontains_multi' ||
                                        data2 === 'not_icontains_multi'
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
    description: 'Sync with nodejs/src/types.ts',
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
                                        data2 === 'starts_with' ||
                                        data2 === 'not_starts_with' ||
                                        data2 === 'ends_with' ||
                                        data2 === 'not_ends_with' ||
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
                                        data2 === 'is_cleaned_path_not_exact' ||
                                        data2 === 'flag_evaluates_to' ||
                                        data2 === 'semver_eq' ||
                                        data2 === 'semver_neq' ||
                                        data2 === 'semver_gt' ||
                                        data2 === 'semver_gte' ||
                                        data2 === 'semver_lt' ||
                                        data2 === 'semver_lte' ||
                                        data2 === 'semver_tilde' ||
                                        data2 === 'semver_caret' ||
                                        data2 === 'semver_wildcard' ||
                                        data2 === 'icontains_multi' ||
                                        data2 === 'not_icontains_multi'
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
const schema26 = {
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
function validate28(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
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
                    if (data.key !== undefined) {
                        const _errs2 = errors
                        if (typeof data.key !== 'string') {
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
                        var valid0 = _errs2 === errors
                    } else {
                        var valid0 = true
                    }
                    if (valid0) {
                        if (data.label !== undefined) {
                            const _errs4 = errors
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
                            var valid0 = _errs4 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.operator !== undefined) {
                                let data2 = data.operator
                                const _errs6 = errors
                                if (typeof data2 !== 'string') {
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
                                        data2 === 'exact' ||
                                        data2 === 'is_not' ||
                                        data2 === 'icontains' ||
                                        data2 === 'not_icontains' ||
                                        data2 === 'starts_with' ||
                                        data2 === 'not_starts_with' ||
                                        data2 === 'ends_with' ||
                                        data2 === 'not_ends_with' ||
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
                                        data2 === 'is_cleaned_path_not_exact' ||
                                        data2 === 'flag_evaluates_to' ||
                                        data2 === 'semver_eq' ||
                                        data2 === 'semver_neq' ||
                                        data2 === 'semver_gt' ||
                                        data2 === 'semver_gte' ||
                                        data2 === 'semver_lt' ||
                                        data2 === 'semver_lte' ||
                                        data2 === 'semver_tilde' ||
                                        data2 === 'semver_caret' ||
                                        data2 === 'semver_wildcard' ||
                                        data2 === 'icontains_multi' ||
                                        data2 === 'not_icontains_multi'
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
                                var valid0 = _errs6 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.type !== undefined) {
                                    let data3 = data.type
                                    const _errs9 = errors
                                    if (typeof data3 !== 'string') {
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
                                    if ('session' !== data3) {
                                        validate28.errors = [
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
    description: 'Sync with nodejs/src/types.ts',
    properties: {
        cohort_deleted: {
            description: 'Set by the feature flag API when the cohort is deleted or does not exist.',
            type: 'boolean',
        },
        cohort_missing: {
            description: 'Set by the feature flag API when the cohort does not exist, so it cannot be restored.',
            type: 'boolean',
        },
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
function validate31(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
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
                validate31.errors = [
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
                            key0 === 'cohort_deleted' ||
                            key0 === 'cohort_missing' ||
                            key0 === 'cohort_name' ||
                            key0 === 'key' ||
                            key0 === 'label' ||
                            key0 === 'operator' ||
                            key0 === 'type' ||
                            key0 === 'value'
                        )
                    ) {
                        validate31.errors = [
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
                    if (data.cohort_deleted !== undefined) {
                        const _errs2 = errors
                        if (typeof data.cohort_deleted !== 'boolean') {
                            validate31.errors = [
                                {
                                    instancePath: instancePath + '/cohort_deleted',
                                    schemaPath: '#/properties/cohort_deleted/type',
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
                        if (data.cohort_missing !== undefined) {
                            const _errs4 = errors
                            if (typeof data.cohort_missing !== 'boolean') {
                                validate31.errors = [
                                    {
                                        instancePath: instancePath + '/cohort_missing',
                                        schemaPath: '#/properties/cohort_missing/type',
                                        keyword: 'type',
                                        params: { type: 'boolean' },
                                        message: 'must be boolean',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs4 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.cohort_name !== undefined) {
                                const _errs6 = errors
                                if (typeof data.cohort_name !== 'string') {
                                    validate31.errors = [
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
                                var valid0 = _errs6 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.key !== undefined) {
                                    let data3 = data.key
                                    const _errs8 = errors
                                    if (typeof data3 !== 'string') {
                                        validate31.errors = [
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
                                    if ('id' !== data3) {
                                        validate31.errors = [
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
                                    var valid0 = _errs8 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.label !== undefined) {
                                        const _errs10 = errors
                                        if (typeof data.label !== 'string') {
                                            validate31.errors = [
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
                                            let data5 = data.operator
                                            const _errs12 = errors
                                            if (typeof data5 !== 'string') {
                                                validate31.errors = [
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
                                                    data5 === 'exact' ||
                                                    data5 === 'is_not' ||
                                                    data5 === 'icontains' ||
                                                    data5 === 'not_icontains' ||
                                                    data5 === 'starts_with' ||
                                                    data5 === 'not_starts_with' ||
                                                    data5 === 'ends_with' ||
                                                    data5 === 'not_ends_with' ||
                                                    data5 === 'regex' ||
                                                    data5 === 'not_regex' ||
                                                    data5 === 'gt' ||
                                                    data5 === 'gte' ||
                                                    data5 === 'lt' ||
                                                    data5 === 'lte' ||
                                                    data5 === 'is_set' ||
                                                    data5 === 'is_not_set' ||
                                                    data5 === 'is_date_exact' ||
                                                    data5 === 'is_date_before' ||
                                                    data5 === 'is_date_after' ||
                                                    data5 === 'between' ||
                                                    data5 === 'not_between' ||
                                                    data5 === 'min' ||
                                                    data5 === 'max' ||
                                                    data5 === 'in' ||
                                                    data5 === 'not_in' ||
                                                    data5 === 'is_cleaned_path_exact' ||
                                                    data5 === 'is_cleaned_path_not_exact' ||
                                                    data5 === 'flag_evaluates_to' ||
                                                    data5 === 'semver_eq' ||
                                                    data5 === 'semver_neq' ||
                                                    data5 === 'semver_gt' ||
                                                    data5 === 'semver_gte' ||
                                                    data5 === 'semver_lt' ||
                                                    data5 === 'semver_lte' ||
                                                    data5 === 'semver_tilde' ||
                                                    data5 === 'semver_caret' ||
                                                    data5 === 'semver_wildcard' ||
                                                    data5 === 'icontains_multi' ||
                                                    data5 === 'not_icontains_multi'
                                                )
                                            ) {
                                                validate31.errors = [
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
                                                let data6 = data.type
                                                const _errs15 = errors
                                                if (typeof data6 !== 'string') {
                                                    validate31.errors = [
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
                                                if ('cohort' !== data6) {
                                                    validate31.errors = [
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
                                                var valid0 = _errs15 === errors
                                            } else {
                                                var valid0 = true
                                            }
                                            if (valid0) {
                                                if (data.value !== undefined) {
                                                    let data7 = data.value
                                                    const _errs17 = errors
                                                    if (
                                                        !(
                                                            typeof data7 == 'number' &&
                                                            !(data7 % 1) &&
                                                            !isNaN(data7) &&
                                                            isFinite(data7)
                                                        )
                                                    ) {
                                                        validate31.errors = [
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
                }
            }
        } else {
            validate31.errors = [
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
    validate31.errors = vErrors
    return errors === 0
}
function validate155(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
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
            if (!validate28(data, { instancePath, parentData, parentDataProperty, rootData })) {
                vErrors = vErrors === null ? validate28.errors : vErrors.concat(validate28.errors)
                errors = vErrors.length
            }
            var _valid0 = _errs3 === errors
            valid0 = valid0 || _valid0
            if (!valid0) {
                const _errs4 = errors
                if (!validate31(data, { instancePath, parentData, parentDataProperty, rootData })) {
                    vErrors = vErrors === null ? validate31.errors : vErrors.concat(validate31.errors)
                    errors = vErrors.length
                }
                var _valid0 = _errs4 === errors
                valid0 = valid0 || _valid0
            }
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
        validate155.errors = vErrors
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
    validate155.errors = vErrors
    return errors === 0
}
function validate154(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (Array.isArray(data)) {
            var valid0 = true
            const len0 = data.length
            for (let i0 = 0; i0 < len0; i0++) {
                const _errs1 = errors
                if (
                    !validate155(data[i0], {
                        instancePath: instancePath + '/' + i0,
                        parentData: data,
                        parentDataProperty: i0,
                        rootData,
                    })
                ) {
                    vErrors = vErrors === null ? validate155.errors : vErrors.concat(validate155.errors)
                    errors = vErrors.length
                }
                var valid0 = _errs1 === errors
                if (!valid0) {
                    break
                }
            }
        } else {
            validate154.errors = [
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
    validate154.errors = vErrors
    return errors === 0
}
export const CompareFilter = validate161
const schema138 = {
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
function validate161(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            const _errs1 = errors
            for (const key0 in data) {
                if (!(key0 === 'compare' || key0 === 'compare_to')) {
                    validate161.errors = [
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
                        validate161.errors = [
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
                            validate161.errors = [
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
            validate161.errors = [
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
    validate161.errors = vErrors
    return errors === 0
}
