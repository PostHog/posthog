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
const schema39 = {
    additionalProperties: false,
    properties: { type: { const: 'empty', type: 'string' } },
    type: 'object',
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
const schema20 = {
    additionalProperties: false,
    description: 'Sync with nodejs/src/types.ts',
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
    description: 'Sync with nodejs/src/types.ts',
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
                                            data3 === 'flag_evaluates_to' ||
                                            data3 === 'semver_eq' ||
                                            data3 === 'semver_neq' ||
                                            data3 === 'semver_gt' ||
                                            data3 === 'semver_gte' ||
                                            data3 === 'semver_lt' ||
                                            data3 === 'semver_lte' ||
                                            data3 === 'semver_tilde' ||
                                            data3 === 'semver_caret' ||
                                            data3 === 'semver_wildcard' ||
                                            data3 === 'icontains_multi' ||
                                            data3 === 'not_icontains_multi'
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
                                            data3 === 'flag_evaluates_to' ||
                                            data3 === 'semver_eq' ||
                                            data3 === 'semver_neq' ||
                                            data3 === 'semver_gt' ||
                                            data3 === 'semver_gte' ||
                                            data3 === 'semver_lt' ||
                                            data3 === 'semver_lte' ||
                                            data3 === 'semver_tilde' ||
                                            data3 === 'semver_caret' ||
                                            data3 === 'semver_wildcard' ||
                                            data3 === 'icontains_multi' ||
                                            data3 === 'not_icontains_multi'
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
        type: { $ref: '#/definitions/LogPropertyFilterType' },
        value: { $ref: '#/definitions/PropertyFilterValue' },
    },
    required: ['key', 'operator', 'type'],
    type: 'object',
}
const schema48 = { enum: ['log', 'log_attribute', 'log_resource_attribute'], type: 'string' }
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
                                                schemaPath: '#/definitions/LogPropertyFilterType/type',
                                                keyword: 'type',
                                                params: { type: 'string' },
                                                message: 'must be string',
                                            },
                                        ]
                                        return false
                                    }
                                    if (
                                        !(
                                            data3 === 'log' ||
                                            data3 === 'log_attribute' ||
                                            data3 === 'log_resource_attribute'
                                        )
                                    ) {
                                        validate54.errors = [
                                            {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/definitions/LogPropertyFilterType/enum',
                                                keyword: 'enum',
                                                params: { allowedValues: schema48.enum },
                                                message: 'must be equal to one of the allowed values',
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
                                        const _errs12 = errors
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
                                        var valid0 = _errs12 === errors
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
const schema49 = {
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
                                                            const _errs29 = errors
                                                            for (const key1 in data) {
                                                                if (!(key1 === 'type')) {
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
                                                            }
                                                            if (_errs29 === errors) {
                                                                if (data.type !== undefined) {
                                                                    let data5 = data.type
                                                                    if (typeof data5 !== 'string') {
                                                                        const err11 = {
                                                                            instancePath: instancePath + '/type',
                                                                            schemaPath:
                                                                                '#/definitions/EmptyPropertyFilter/properties/type/type',
                                                                            keyword: 'type',
                                                                            params: { type: 'string' },
                                                                            message: 'must be string',
                                                                        }
                                                                        if (vErrors === null) {
                                                                            vErrors = [err11]
                                                                        } else {
                                                                            vErrors.push(err11)
                                                                        }
                                                                        errors++
                                                                    }
                                                                    if ('empty' !== data5) {
                                                                        const err12 = {
                                                                            instancePath: instancePath + '/type',
                                                                            schemaPath:
                                                                                '#/definitions/EmptyPropertyFilter/properties/type/const',
                                                                            keyword: 'const',
                                                                            params: { allowedValue: 'empty' },
                                                                            message: 'must be equal to constant',
                                                                        }
                                                                        if (vErrors === null) {
                                                                            vErrors = [err12]
                                                                        } else {
                                                                            vErrors.push(err12)
                                                                        }
                                                                        errors++
                                                                    }
                                                                }
                                                            }
                                                        } else {
                                                            const err13 = {
                                                                instancePath,
                                                                schemaPath: '#/definitions/EmptyPropertyFilter/type',
                                                                keyword: 'type',
                                                                params: { type: 'object' },
                                                                message: 'must be object',
                                                            }
                                                            if (vErrors === null) {
                                                                vErrors = [err13]
                                                            } else {
                                                                vErrors.push(err13)
                                                            }
                                                            errors++
                                                        }
                                                    }
                                                    var _valid0 = _errs26 === errors
                                                    valid0 = valid0 || _valid0
                                                    if (!valid0) {
                                                        const _errs32 = errors
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
                                                        var _valid0 = _errs32 === errors
                                                        valid0 = valid0 || _valid0
                                                        if (!valid0) {
                                                            const _errs33 = errors
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
                                                            var _valid0 = _errs33 === errors
                                                            valid0 = valid0 || _valid0
                                                            if (!valid0) {
                                                                const _errs34 = errors
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
                                                                var _valid0 = _errs34 === errors
                                                                valid0 = valid0 || _valid0
                                                                if (!valid0) {
                                                                    const _errs35 = errors
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
                                                                    var _valid0 = _errs35 === errors
                                                                    valid0 = valid0 || _valid0
                                                                    if (!valid0) {
                                                                        const _errs36 = errors
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
                                                                        var _valid0 = _errs36 === errors
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
        const err14 = {
            instancePath,
            schemaPath: '#/anyOf',
            keyword: 'anyOf',
            params: {},
            message: 'must match a schema in anyOf',
        }
        if (vErrors === null) {
            vErrors = [err14]
        } else {
            vErrors.push(err14)
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
const schema51 = { items: { $ref: '#/definitions/WebAnalyticsPropertyFilter' }, type: 'array' }
const schema52 = {
    anyOf: [
        { $ref: '#/definitions/EventPropertyFilter' },
        { $ref: '#/definitions/PersonPropertyFilter' },
        { $ref: '#/definitions/SessionPropertyFilter' },
        { $ref: '#/definitions/CohortPropertyFilter' },
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
            if (!valid0) {
                const _errs4 = errors
                if (!validate28(data, { instancePath, parentData, parentDataProperty, rootData })) {
                    vErrors = vErrors === null ? validate28.errors : vErrors.concat(validate28.errors)
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
export const RevenueAnalyticsPropertyFilters = validate67
const schema53 = { items: { $ref: '#/definitions/RevenueAnalyticsPropertyFilter' }, type: 'array' }
function validate67(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
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
            validate67.errors = [
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
    validate67.errors = vErrors
    return errors === 0
}
export const SessionPropertyFilter = validate69
function validate69(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
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
                validate69.errors = [
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
                        validate69.errors = [
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
                            validate69.errors = [
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
                                validate69.errors = [
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
                                    validate69.errors = [
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
                                    validate69.errors = [
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
                                        validate69.errors = [
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
                                        validate69.errors = [
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
            validate69.errors = [
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
    validate69.errors = vErrors
    return errors === 0
}
export const CompareFilter = validate71
const schema56 = {
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
function validate71(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            const _errs1 = errors
            for (const key0 in data) {
                if (!(key0 === 'compare' || key0 === 'compare_to')) {
                    validate71.errors = [
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
                        validate71.errors = [
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
                            validate71.errors = [
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
            validate71.errors = [
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
    validate71.errors = vErrors
    return errors === 0
}
export const ExperimentMetric = validate72
const schema57 = {
    anyOf: [
        { $ref: '#/definitions/ExperimentMeanMetric' },
        { $ref: '#/definitions/ExperimentFunnelMetric' },
        { $ref: '#/definitions/ExperimentRatioMetric' },
        { $ref: '#/definitions/ExperimentRetentionMetric' },
    ],
}
const schema58 = {
    additionalProperties: false,
    properties: {
        breakdownFilter: { $ref: '#/definitions/BreakdownFilter' },
        conversion_window: { $ref: '#/definitions/integer' },
        conversion_window_unit: { $ref: '#/definitions/FunnelConversionWindowTimeUnit' },
        fingerprint: { type: 'string' },
        goal: { $ref: '#/definitions/ExperimentMetricGoal' },
        ignore_zeros: { type: 'boolean' },
        isSharedMetric: { type: 'boolean' },
        kind: { const: 'ExperimentMetric', type: 'string' },
        lower_bound_percentile: { type: 'number' },
        metric_type: { const: 'mean', type: 'string' },
        name: { type: 'string' },
        response: { type: 'object' },
        sharedMetricId: { type: 'number' },
        source: { $ref: '#/definitions/ExperimentMetricSource' },
        upper_bound_percentile: { type: 'number' },
        uuid: { type: 'string' },
        version: { description: 'version of the node, used for schema migrations', type: 'number' },
    },
    required: ['kind', 'metric_type', 'source'],
    type: 'object',
}
const schema60 = { type: 'integer' }
const schema72 = { enum: ['second', 'minute', 'hour', 'day', 'week', 'month'], type: 'string' }
const schema73 = { enum: ['increase', 'decrease'], type: 'string' }
const func2 = Object.prototype.hasOwnProperty
const schema59 = {
    additionalProperties: false,
    properties: {
        breakdown: {
            anyOf: [
                { type: 'string' },
                { $ref: '#/definitions/integer' },
                { items: { anyOf: [{ type: 'string' }, { $ref: '#/definitions/integer' }] }, type: 'array' },
                { type: 'null' },
            ],
        },
        breakdown_group_type_index: { anyOf: [{ $ref: '#/definitions/integer' }, { type: 'null' }] },
        breakdown_hide_other_aggregation: { type: ['boolean', 'null'] },
        breakdown_histogram_bin_count: { $ref: '#/definitions/integer' },
        breakdown_limit: { $ref: '#/definitions/integer' },
        breakdown_normalize_url: { type: 'boolean' },
        breakdown_path_cleaning: { type: 'boolean' },
        breakdown_type: { anyOf: [{ $ref: '#/definitions/BreakdownType' }, { type: 'null' }], default: 'event' },
        breakdowns: { items: { $ref: '#/definitions/Breakdown' }, maxItems: 3, type: 'array' },
    },
    type: 'object',
}
const schema65 = {
    enum: [
        'cohort',
        'person',
        'event',
        'event_metadata',
        'group',
        'session',
        'hogql',
        'data_warehouse',
        'data_warehouse_person_property',
        'revenue_analytics',
    ],
    type: 'string',
}
const schema66 = {
    additionalProperties: false,
    properties: {
        group_type_index: { anyOf: [{ $ref: '#/definitions/integer' }, { type: 'null' }] },
        histogram_bin_count: { $ref: '#/definitions/integer' },
        normalize_url: { type: 'boolean' },
        property: { anyOf: [{ type: 'string' }, { $ref: '#/definitions/integer' }] },
        type: { anyOf: [{ $ref: '#/definitions/MultipleBreakdownType' }, { type: 'null' }] },
    },
    required: ['property'],
    type: 'object',
}
const schema70 = {
    enum: ['cohort', 'person', 'event', 'event_metadata', 'group', 'session', 'hogql', 'revenue_analytics'],
    type: 'string',
}
function validate75(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if (data.property === undefined && (missing0 = 'property')) {
                validate75.errors = [
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
                            key0 === 'histogram_bin_count' ||
                            key0 === 'normalize_url' ||
                            key0 === 'property' ||
                            key0 === 'type'
                        )
                    ) {
                        validate75.errors = [
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
                                schemaPath: '#/definitions/integer/type',
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
                            const _errs7 = errors
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
                            var _valid0 = _errs7 === errors
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
                            validate75.errors = vErrors
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
                        if (data.histogram_bin_count !== undefined) {
                            let data1 = data.histogram_bin_count
                            const _errs9 = errors
                            if (!(typeof data1 == 'number' && !(data1 % 1) && !isNaN(data1) && isFinite(data1))) {
                                validate75.errors = [
                                    {
                                        instancePath: instancePath + '/histogram_bin_count',
                                        schemaPath: '#/definitions/integer/type',
                                        keyword: 'type',
                                        params: { type: 'integer' },
                                        message: 'must be integer',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs9 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.normalize_url !== undefined) {
                                const _errs12 = errors
                                if (typeof data.normalize_url !== 'boolean') {
                                    validate75.errors = [
                                        {
                                            instancePath: instancePath + '/normalize_url',
                                            schemaPath: '#/properties/normalize_url/type',
                                            keyword: 'type',
                                            params: { type: 'boolean' },
                                            message: 'must be boolean',
                                        },
                                    ]
                                    return false
                                }
                                var valid0 = _errs12 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.property !== undefined) {
                                    let data3 = data.property
                                    const _errs14 = errors
                                    const _errs15 = errors
                                    let valid4 = false
                                    const _errs16 = errors
                                    if (typeof data3 !== 'string') {
                                        const err3 = {
                                            instancePath: instancePath + '/property',
                                            schemaPath: '#/properties/property/anyOf/0/type',
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
                                    var _valid1 = _errs16 === errors
                                    valid4 = valid4 || _valid1
                                    if (!valid4) {
                                        const _errs18 = errors
                                        if (
                                            !(
                                                typeof data3 == 'number' &&
                                                !(data3 % 1) &&
                                                !isNaN(data3) &&
                                                isFinite(data3)
                                            )
                                        ) {
                                            const err4 = {
                                                instancePath: instancePath + '/property',
                                                schemaPath: '#/definitions/integer/type',
                                                keyword: 'type',
                                                params: { type: 'integer' },
                                                message: 'must be integer',
                                            }
                                            if (vErrors === null) {
                                                vErrors = [err4]
                                            } else {
                                                vErrors.push(err4)
                                            }
                                            errors++
                                        }
                                        var _valid1 = _errs18 === errors
                                        valid4 = valid4 || _valid1
                                    }
                                    if (!valid4) {
                                        const err5 = {
                                            instancePath: instancePath + '/property',
                                            schemaPath: '#/properties/property/anyOf',
                                            keyword: 'anyOf',
                                            params: {},
                                            message: 'must match a schema in anyOf',
                                        }
                                        if (vErrors === null) {
                                            vErrors = [err5]
                                        } else {
                                            vErrors.push(err5)
                                        }
                                        errors++
                                        validate75.errors = vErrors
                                        return false
                                    } else {
                                        errors = _errs15
                                        if (vErrors !== null) {
                                            if (_errs15) {
                                                vErrors.length = _errs15
                                            } else {
                                                vErrors = null
                                            }
                                        }
                                    }
                                    var valid0 = _errs14 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.type !== undefined) {
                                        let data4 = data.type
                                        const _errs21 = errors
                                        const _errs22 = errors
                                        let valid6 = false
                                        const _errs23 = errors
                                        if (typeof data4 !== 'string') {
                                            const err6 = {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/definitions/MultipleBreakdownType/type',
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
                                        if (
                                            !(
                                                data4 === 'cohort' ||
                                                data4 === 'person' ||
                                                data4 === 'event' ||
                                                data4 === 'event_metadata' ||
                                                data4 === 'group' ||
                                                data4 === 'session' ||
                                                data4 === 'hogql' ||
                                                data4 === 'revenue_analytics'
                                            )
                                        ) {
                                            const err7 = {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/definitions/MultipleBreakdownType/enum',
                                                keyword: 'enum',
                                                params: { allowedValues: schema70.enum },
                                                message: 'must be equal to one of the allowed values',
                                            }
                                            if (vErrors === null) {
                                                vErrors = [err7]
                                            } else {
                                                vErrors.push(err7)
                                            }
                                            errors++
                                        }
                                        var _valid2 = _errs23 === errors
                                        valid6 = valid6 || _valid2
                                        if (!valid6) {
                                            const _errs26 = errors
                                            if (data4 !== null) {
                                                const err8 = {
                                                    instancePath: instancePath + '/type',
                                                    schemaPath: '#/properties/type/anyOf/1/type',
                                                    keyword: 'type',
                                                    params: { type: 'null' },
                                                    message: 'must be null',
                                                }
                                                if (vErrors === null) {
                                                    vErrors = [err8]
                                                } else {
                                                    vErrors.push(err8)
                                                }
                                                errors++
                                            }
                                            var _valid2 = _errs26 === errors
                                            valid6 = valid6 || _valid2
                                        }
                                        if (!valid6) {
                                            const err9 = {
                                                instancePath: instancePath + '/type',
                                                schemaPath: '#/properties/type/anyOf',
                                                keyword: 'anyOf',
                                                params: {},
                                                message: 'must match a schema in anyOf',
                                            }
                                            if (vErrors === null) {
                                                vErrors = [err9]
                                            } else {
                                                vErrors.push(err9)
                                            }
                                            errors++
                                            validate75.errors = vErrors
                                            return false
                                        } else {
                                            errors = _errs22
                                            if (vErrors !== null) {
                                                if (_errs22) {
                                                    vErrors.length = _errs22
                                                } else {
                                                    vErrors = null
                                                }
                                            }
                                        }
                                        var valid0 = _errs21 === errors
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
            validate75.errors = [
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
    validate75.errors = vErrors
    return errors === 0
}
function validate74(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            const _errs1 = errors
            for (const key0 in data) {
                if (!func2.call(schema59.properties, key0)) {
                    validate74.errors = [
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
                if (data.breakdown !== undefined) {
                    let data0 = data.breakdown
                    const _errs2 = errors
                    const _errs3 = errors
                    let valid1 = false
                    const _errs4 = errors
                    if (typeof data0 !== 'string') {
                        const err0 = {
                            instancePath: instancePath + '/breakdown',
                            schemaPath: '#/properties/breakdown/anyOf/0/type',
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
                    var _valid0 = _errs4 === errors
                    valid1 = valid1 || _valid0
                    if (!valid1) {
                        const _errs6 = errors
                        if (!(typeof data0 == 'number' && !(data0 % 1) && !isNaN(data0) && isFinite(data0))) {
                            const err1 = {
                                instancePath: instancePath + '/breakdown',
                                schemaPath: '#/definitions/integer/type',
                                keyword: 'type',
                                params: { type: 'integer' },
                                message: 'must be integer',
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
                        if (!valid1) {
                            const _errs9 = errors
                            if (errors === _errs9) {
                                if (Array.isArray(data0)) {
                                    var valid3 = true
                                    const len0 = data0.length
                                    for (let i0 = 0; i0 < len0; i0++) {
                                        let data1 = data0[i0]
                                        const _errs11 = errors
                                        const _errs12 = errors
                                        let valid4 = false
                                        const _errs13 = errors
                                        if (typeof data1 !== 'string') {
                                            const err2 = {
                                                instancePath: instancePath + '/breakdown/' + i0,
                                                schemaPath: '#/properties/breakdown/anyOf/2/items/anyOf/0/type',
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
                                        var _valid1 = _errs13 === errors
                                        valid4 = valid4 || _valid1
                                        if (!valid4) {
                                            const _errs15 = errors
                                            if (
                                                !(
                                                    typeof data1 == 'number' &&
                                                    !(data1 % 1) &&
                                                    !isNaN(data1) &&
                                                    isFinite(data1)
                                                )
                                            ) {
                                                const err3 = {
                                                    instancePath: instancePath + '/breakdown/' + i0,
                                                    schemaPath: '#/definitions/integer/type',
                                                    keyword: 'type',
                                                    params: { type: 'integer' },
                                                    message: 'must be integer',
                                                }
                                                if (vErrors === null) {
                                                    vErrors = [err3]
                                                } else {
                                                    vErrors.push(err3)
                                                }
                                                errors++
                                            }
                                            var _valid1 = _errs15 === errors
                                            valid4 = valid4 || _valid1
                                        }
                                        if (!valid4) {
                                            const err4 = {
                                                instancePath: instancePath + '/breakdown/' + i0,
                                                schemaPath: '#/properties/breakdown/anyOf/2/items/anyOf',
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
                                        } else {
                                            errors = _errs12
                                            if (vErrors !== null) {
                                                if (_errs12) {
                                                    vErrors.length = _errs12
                                                } else {
                                                    vErrors = null
                                                }
                                            }
                                        }
                                        var valid3 = _errs11 === errors
                                        if (!valid3) {
                                            break
                                        }
                                    }
                                } else {
                                    const err5 = {
                                        instancePath: instancePath + '/breakdown',
                                        schemaPath: '#/properties/breakdown/anyOf/2/type',
                                        keyword: 'type',
                                        params: { type: 'array' },
                                        message: 'must be array',
                                    }
                                    if (vErrors === null) {
                                        vErrors = [err5]
                                    } else {
                                        vErrors.push(err5)
                                    }
                                    errors++
                                }
                            }
                            var _valid0 = _errs9 === errors
                            valid1 = valid1 || _valid0
                            if (!valid1) {
                                const _errs18 = errors
                                if (data0 !== null) {
                                    const err6 = {
                                        instancePath: instancePath + '/breakdown',
                                        schemaPath: '#/properties/breakdown/anyOf/3/type',
                                        keyword: 'type',
                                        params: { type: 'null' },
                                        message: 'must be null',
                                    }
                                    if (vErrors === null) {
                                        vErrors = [err6]
                                    } else {
                                        vErrors.push(err6)
                                    }
                                    errors++
                                }
                                var _valid0 = _errs18 === errors
                                valid1 = valid1 || _valid0
                            }
                        }
                    }
                    if (!valid1) {
                        const err7 = {
                            instancePath: instancePath + '/breakdown',
                            schemaPath: '#/properties/breakdown/anyOf',
                            keyword: 'anyOf',
                            params: {},
                            message: 'must match a schema in anyOf',
                        }
                        if (vErrors === null) {
                            vErrors = [err7]
                        } else {
                            vErrors.push(err7)
                        }
                        errors++
                        validate74.errors = vErrors
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
                    if (data.breakdown_group_type_index !== undefined) {
                        let data2 = data.breakdown_group_type_index
                        const _errs20 = errors
                        const _errs21 = errors
                        let valid6 = false
                        const _errs22 = errors
                        if (!(typeof data2 == 'number' && !(data2 % 1) && !isNaN(data2) && isFinite(data2))) {
                            const err8 = {
                                instancePath: instancePath + '/breakdown_group_type_index',
                                schemaPath: '#/definitions/integer/type',
                                keyword: 'type',
                                params: { type: 'integer' },
                                message: 'must be integer',
                            }
                            if (vErrors === null) {
                                vErrors = [err8]
                            } else {
                                vErrors.push(err8)
                            }
                            errors++
                        }
                        var _valid2 = _errs22 === errors
                        valid6 = valid6 || _valid2
                        if (!valid6) {
                            const _errs25 = errors
                            if (data2 !== null) {
                                const err9 = {
                                    instancePath: instancePath + '/breakdown_group_type_index',
                                    schemaPath: '#/properties/breakdown_group_type_index/anyOf/1/type',
                                    keyword: 'type',
                                    params: { type: 'null' },
                                    message: 'must be null',
                                }
                                if (vErrors === null) {
                                    vErrors = [err9]
                                } else {
                                    vErrors.push(err9)
                                }
                                errors++
                            }
                            var _valid2 = _errs25 === errors
                            valid6 = valid6 || _valid2
                        }
                        if (!valid6) {
                            const err10 = {
                                instancePath: instancePath + '/breakdown_group_type_index',
                                schemaPath: '#/properties/breakdown_group_type_index/anyOf',
                                keyword: 'anyOf',
                                params: {},
                                message: 'must match a schema in anyOf',
                            }
                            if (vErrors === null) {
                                vErrors = [err10]
                            } else {
                                vErrors.push(err10)
                            }
                            errors++
                            validate74.errors = vErrors
                            return false
                        } else {
                            errors = _errs21
                            if (vErrors !== null) {
                                if (_errs21) {
                                    vErrors.length = _errs21
                                } else {
                                    vErrors = null
                                }
                            }
                        }
                        var valid0 = _errs20 === errors
                    } else {
                        var valid0 = true
                    }
                    if (valid0) {
                        if (data.breakdown_hide_other_aggregation !== undefined) {
                            let data3 = data.breakdown_hide_other_aggregation
                            const _errs27 = errors
                            if (typeof data3 !== 'boolean' && data3 !== null) {
                                validate74.errors = [
                                    {
                                        instancePath: instancePath + '/breakdown_hide_other_aggregation',
                                        schemaPath: '#/properties/breakdown_hide_other_aggregation/type',
                                        keyword: 'type',
                                        params: { type: schema59.properties.breakdown_hide_other_aggregation.type },
                                        message: 'must be boolean,null',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs27 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.breakdown_histogram_bin_count !== undefined) {
                                let data4 = data.breakdown_histogram_bin_count
                                const _errs29 = errors
                                if (!(typeof data4 == 'number' && !(data4 % 1) && !isNaN(data4) && isFinite(data4))) {
                                    validate74.errors = [
                                        {
                                            instancePath: instancePath + '/breakdown_histogram_bin_count',
                                            schemaPath: '#/definitions/integer/type',
                                            keyword: 'type',
                                            params: { type: 'integer' },
                                            message: 'must be integer',
                                        },
                                    ]
                                    return false
                                }
                                var valid0 = _errs29 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.breakdown_limit !== undefined) {
                                    let data5 = data.breakdown_limit
                                    const _errs32 = errors
                                    if (
                                        !(typeof data5 == 'number' && !(data5 % 1) && !isNaN(data5) && isFinite(data5))
                                    ) {
                                        validate74.errors = [
                                            {
                                                instancePath: instancePath + '/breakdown_limit',
                                                schemaPath: '#/definitions/integer/type',
                                                keyword: 'type',
                                                params: { type: 'integer' },
                                                message: 'must be integer',
                                            },
                                        ]
                                        return false
                                    }
                                    var valid0 = _errs32 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.breakdown_normalize_url !== undefined) {
                                        const _errs35 = errors
                                        if (typeof data.breakdown_normalize_url !== 'boolean') {
                                            validate74.errors = [
                                                {
                                                    instancePath: instancePath + '/breakdown_normalize_url',
                                                    schemaPath: '#/properties/breakdown_normalize_url/type',
                                                    keyword: 'type',
                                                    params: { type: 'boolean' },
                                                    message: 'must be boolean',
                                                },
                                            ]
                                            return false
                                        }
                                        var valid0 = _errs35 === errors
                                    } else {
                                        var valid0 = true
                                    }
                                    if (valid0) {
                                        if (data.breakdown_path_cleaning !== undefined) {
                                            const _errs37 = errors
                                            if (typeof data.breakdown_path_cleaning !== 'boolean') {
                                                validate74.errors = [
                                                    {
                                                        instancePath: instancePath + '/breakdown_path_cleaning',
                                                        schemaPath: '#/properties/breakdown_path_cleaning/type',
                                                        keyword: 'type',
                                                        params: { type: 'boolean' },
                                                        message: 'must be boolean',
                                                    },
                                                ]
                                                return false
                                            }
                                            var valid0 = _errs37 === errors
                                        } else {
                                            var valid0 = true
                                        }
                                        if (valid0) {
                                            if (data.breakdown_type !== undefined) {
                                                let data8 = data.breakdown_type
                                                const _errs39 = errors
                                                const _errs40 = errors
                                                let valid10 = false
                                                const _errs41 = errors
                                                if (typeof data8 !== 'string') {
                                                    const err11 = {
                                                        instancePath: instancePath + '/breakdown_type',
                                                        schemaPath: '#/definitions/BreakdownType/type',
                                                        keyword: 'type',
                                                        params: { type: 'string' },
                                                        message: 'must be string',
                                                    }
                                                    if (vErrors === null) {
                                                        vErrors = [err11]
                                                    } else {
                                                        vErrors.push(err11)
                                                    }
                                                    errors++
                                                }
                                                if (
                                                    !(
                                                        data8 === 'cohort' ||
                                                        data8 === 'person' ||
                                                        data8 === 'event' ||
                                                        data8 === 'event_metadata' ||
                                                        data8 === 'group' ||
                                                        data8 === 'session' ||
                                                        data8 === 'hogql' ||
                                                        data8 === 'data_warehouse' ||
                                                        data8 === 'data_warehouse_person_property' ||
                                                        data8 === 'revenue_analytics'
                                                    )
                                                ) {
                                                    const err12 = {
                                                        instancePath: instancePath + '/breakdown_type',
                                                        schemaPath: '#/definitions/BreakdownType/enum',
                                                        keyword: 'enum',
                                                        params: { allowedValues: schema65.enum },
                                                        message: 'must be equal to one of the allowed values',
                                                    }
                                                    if (vErrors === null) {
                                                        vErrors = [err12]
                                                    } else {
                                                        vErrors.push(err12)
                                                    }
                                                    errors++
                                                }
                                                var _valid3 = _errs41 === errors
                                                valid10 = valid10 || _valid3
                                                if (!valid10) {
                                                    const _errs44 = errors
                                                    if (data8 !== null) {
                                                        const err13 = {
                                                            instancePath: instancePath + '/breakdown_type',
                                                            schemaPath: '#/properties/breakdown_type/anyOf/1/type',
                                                            keyword: 'type',
                                                            params: { type: 'null' },
                                                            message: 'must be null',
                                                        }
                                                        if (vErrors === null) {
                                                            vErrors = [err13]
                                                        } else {
                                                            vErrors.push(err13)
                                                        }
                                                        errors++
                                                    }
                                                    var _valid3 = _errs44 === errors
                                                    valid10 = valid10 || _valid3
                                                }
                                                if (!valid10) {
                                                    const err14 = {
                                                        instancePath: instancePath + '/breakdown_type',
                                                        schemaPath: '#/properties/breakdown_type/anyOf',
                                                        keyword: 'anyOf',
                                                        params: {},
                                                        message: 'must match a schema in anyOf',
                                                    }
                                                    if (vErrors === null) {
                                                        vErrors = [err14]
                                                    } else {
                                                        vErrors.push(err14)
                                                    }
                                                    errors++
                                                    validate74.errors = vErrors
                                                    return false
                                                } else {
                                                    errors = _errs40
                                                    if (vErrors !== null) {
                                                        if (_errs40) {
                                                            vErrors.length = _errs40
                                                        } else {
                                                            vErrors = null
                                                        }
                                                    }
                                                }
                                                var valid0 = _errs39 === errors
                                            } else {
                                                var valid0 = true
                                            }
                                            if (valid0) {
                                                if (data.breakdowns !== undefined) {
                                                    let data9 = data.breakdowns
                                                    const _errs46 = errors
                                                    if (errors === _errs46) {
                                                        if (Array.isArray(data9)) {
                                                            if (data9.length > 3) {
                                                                validate74.errors = [
                                                                    {
                                                                        instancePath: instancePath + '/breakdowns',
                                                                        schemaPath: '#/properties/breakdowns/maxItems',
                                                                        keyword: 'maxItems',
                                                                        params: { limit: 3 },
                                                                        message: 'must NOT have more than 3 items',
                                                                    },
                                                                ]
                                                                return false
                                                            } else {
                                                                var valid12 = true
                                                                const len1 = data9.length
                                                                for (let i1 = 0; i1 < len1; i1++) {
                                                                    const _errs48 = errors
                                                                    if (
                                                                        !validate75(data9[i1], {
                                                                            instancePath:
                                                                                instancePath + '/breakdowns/' + i1,
                                                                            parentData: data9,
                                                                            parentDataProperty: i1,
                                                                            rootData,
                                                                        })
                                                                    ) {
                                                                        vErrors =
                                                                            vErrors === null
                                                                                ? validate75.errors
                                                                                : vErrors.concat(validate75.errors)
                                                                        errors = vErrors.length
                                                                    }
                                                                    var valid12 = _errs48 === errors
                                                                    if (!valid12) {
                                                                        break
                                                                    }
                                                                }
                                                            }
                                                        } else {
                                                            validate74.errors = [
                                                                {
                                                                    instancePath: instancePath + '/breakdowns',
                                                                    schemaPath: '#/properties/breakdowns/type',
                                                                    keyword: 'type',
                                                                    params: { type: 'array' },
                                                                    message: 'must be array',
                                                                },
                                                            ]
                                                            return false
                                                        }
                                                    }
                                                    var valid0 = _errs46 === errors
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
            validate74.errors = [
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
    validate74.errors = vErrors
    return errors === 0
}
const schema74 = {
    anyOf: [
        { $ref: '#/definitions/EventsNode' },
        { $ref: '#/definitions/ActionsNode' },
        { $ref: '#/definitions/ExperimentDataWarehouseNode' },
    ],
}
const schema75 = {
    additionalProperties: false,
    properties: {
        custom_name: { type: 'string' },
        event: { description: 'The event or `null` for all events.', type: ['string', 'null'] },
        fixedProperties: {
            description:
                "Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
            items: { $ref: '#/definitions/AnyPropertyFilter' },
            type: 'array',
        },
        kind: { const: 'EventsNode', type: 'string' },
        limit: { $ref: '#/definitions/integer' },
        math: { $ref: '#/definitions/MathType' },
        math_group_type_index: { enum: [0, 1, 2, 3, 4], type: 'number' },
        math_hogql: { type: 'string' },
        math_multiplier: { type: 'number' },
        math_property: { type: 'string' },
        math_property_revenue_currency: { $ref: '#/definitions/RevenueCurrencyPropertyConfig' },
        math_property_type: { type: 'string' },
        name: { type: 'string' },
        optionalInFunnel: { type: 'boolean' },
        orderBy: { description: 'Columns to order by', items: { type: 'string' }, type: 'array' },
        properties: {
            description: 'Properties configurable in the interface',
            items: { $ref: '#/definitions/AnyPropertyFilter' },
            type: 'array',
        },
        response: { type: 'object' },
        version: { description: 'version of the node, used for schema migrations', type: 'number' },
    },
    required: ['kind'],
    type: 'object',
}
const schema77 = {
    anyOf: [
        { $ref: '#/definitions/BaseMathType' },
        { $ref: '#/definitions/FunnelMathType' },
        { $ref: '#/definitions/PropertyMathType' },
        { $ref: '#/definitions/CountPerActorMathType' },
        { $ref: '#/definitions/GroupMathType' },
        { $ref: '#/definitions/HogQLMathType' },
        { $ref: '#/definitions/ExperimentMetricMathType' },
        { $ref: '#/definitions/CalendarHeatmapMathType' },
    ],
}
const schema78 = {
    enum: [
        'total',
        'dau',
        'weekly_active',
        'monthly_active',
        'unique_session',
        'first_time_for_user',
        'first_matching_event_for_user',
    ],
    type: 'string',
}
const schema79 = { enum: ['total', 'first_time_for_user', 'first_time_for_user_with_filters'], type: 'string' }
const schema80 = { enum: ['avg', 'sum', 'min', 'max', 'median', 'p75', 'p90', 'p95', 'p99'], type: 'string' }
const schema81 = {
    enum: [
        'avg_count_per_actor',
        'min_count_per_actor',
        'max_count_per_actor',
        'median_count_per_actor',
        'p75_count_per_actor',
        'p90_count_per_actor',
        'p95_count_per_actor',
        'p99_count_per_actor',
    ],
    type: 'string',
}
const schema82 = { const: 'unique_group', type: 'string' }
const schema83 = { const: 'hogql', type: 'string' }
const schema84 = {
    enum: ['total', 'sum', 'unique_session', 'min', 'max', 'avg', 'dau', 'unique_group', 'hogql'],
    type: 'string',
}
const schema85 = { enum: ['total', 'dau'], type: 'string' }
function validate81(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    const _errs0 = errors
    let valid0 = false
    const _errs1 = errors
    if (typeof data !== 'string') {
        const err0 = {
            instancePath,
            schemaPath: '#/definitions/BaseMathType/type',
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
    if (
        !(
            data === 'total' ||
            data === 'dau' ||
            data === 'weekly_active' ||
            data === 'monthly_active' ||
            data === 'unique_session' ||
            data === 'first_time_for_user' ||
            data === 'first_matching_event_for_user'
        )
    ) {
        const err1 = {
            instancePath,
            schemaPath: '#/definitions/BaseMathType/enum',
            keyword: 'enum',
            params: { allowedValues: schema78.enum },
            message: 'must be equal to one of the allowed values',
        }
        if (vErrors === null) {
            vErrors = [err1]
        } else {
            vErrors.push(err1)
        }
        errors++
    }
    var _valid0 = _errs1 === errors
    valid0 = valid0 || _valid0
    if (!valid0) {
        const _errs4 = errors
        if (typeof data !== 'string') {
            const err2 = {
                instancePath,
                schemaPath: '#/definitions/FunnelMathType/type',
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
        if (!(data === 'total' || data === 'first_time_for_user' || data === 'first_time_for_user_with_filters')) {
            const err3 = {
                instancePath,
                schemaPath: '#/definitions/FunnelMathType/enum',
                keyword: 'enum',
                params: { allowedValues: schema79.enum },
                message: 'must be equal to one of the allowed values',
            }
            if (vErrors === null) {
                vErrors = [err3]
            } else {
                vErrors.push(err3)
            }
            errors++
        }
        var _valid0 = _errs4 === errors
        valid0 = valid0 || _valid0
        if (!valid0) {
            const _errs7 = errors
            if (typeof data !== 'string') {
                const err4 = {
                    instancePath,
                    schemaPath: '#/definitions/PropertyMathType/type',
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
            if (
                !(
                    data === 'avg' ||
                    data === 'sum' ||
                    data === 'min' ||
                    data === 'max' ||
                    data === 'median' ||
                    data === 'p75' ||
                    data === 'p90' ||
                    data === 'p95' ||
                    data === 'p99'
                )
            ) {
                const err5 = {
                    instancePath,
                    schemaPath: '#/definitions/PropertyMathType/enum',
                    keyword: 'enum',
                    params: { allowedValues: schema80.enum },
                    message: 'must be equal to one of the allowed values',
                }
                if (vErrors === null) {
                    vErrors = [err5]
                } else {
                    vErrors.push(err5)
                }
                errors++
            }
            var _valid0 = _errs7 === errors
            valid0 = valid0 || _valid0
            if (!valid0) {
                const _errs10 = errors
                if (typeof data !== 'string') {
                    const err6 = {
                        instancePath,
                        schemaPath: '#/definitions/CountPerActorMathType/type',
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
                if (
                    !(
                        data === 'avg_count_per_actor' ||
                        data === 'min_count_per_actor' ||
                        data === 'max_count_per_actor' ||
                        data === 'median_count_per_actor' ||
                        data === 'p75_count_per_actor' ||
                        data === 'p90_count_per_actor' ||
                        data === 'p95_count_per_actor' ||
                        data === 'p99_count_per_actor'
                    )
                ) {
                    const err7 = {
                        instancePath,
                        schemaPath: '#/definitions/CountPerActorMathType/enum',
                        keyword: 'enum',
                        params: { allowedValues: schema81.enum },
                        message: 'must be equal to one of the allowed values',
                    }
                    if (vErrors === null) {
                        vErrors = [err7]
                    } else {
                        vErrors.push(err7)
                    }
                    errors++
                }
                var _valid0 = _errs10 === errors
                valid0 = valid0 || _valid0
                if (!valid0) {
                    const _errs13 = errors
                    if (typeof data !== 'string') {
                        const err8 = {
                            instancePath,
                            schemaPath: '#/definitions/GroupMathType/type',
                            keyword: 'type',
                            params: { type: 'string' },
                            message: 'must be string',
                        }
                        if (vErrors === null) {
                            vErrors = [err8]
                        } else {
                            vErrors.push(err8)
                        }
                        errors++
                    }
                    if ('unique_group' !== data) {
                        const err9 = {
                            instancePath,
                            schemaPath: '#/definitions/GroupMathType/const',
                            keyword: 'const',
                            params: { allowedValue: 'unique_group' },
                            message: 'must be equal to constant',
                        }
                        if (vErrors === null) {
                            vErrors = [err9]
                        } else {
                            vErrors.push(err9)
                        }
                        errors++
                    }
                    var _valid0 = _errs13 === errors
                    valid0 = valid0 || _valid0
                    if (!valid0) {
                        const _errs16 = errors
                        if (typeof data !== 'string') {
                            const err10 = {
                                instancePath,
                                schemaPath: '#/definitions/HogQLMathType/type',
                                keyword: 'type',
                                params: { type: 'string' },
                                message: 'must be string',
                            }
                            if (vErrors === null) {
                                vErrors = [err10]
                            } else {
                                vErrors.push(err10)
                            }
                            errors++
                        }
                        if ('hogql' !== data) {
                            const err11 = {
                                instancePath,
                                schemaPath: '#/definitions/HogQLMathType/const',
                                keyword: 'const',
                                params: { allowedValue: 'hogql' },
                                message: 'must be equal to constant',
                            }
                            if (vErrors === null) {
                                vErrors = [err11]
                            } else {
                                vErrors.push(err11)
                            }
                            errors++
                        }
                        var _valid0 = _errs16 === errors
                        valid0 = valid0 || _valid0
                        if (!valid0) {
                            const _errs19 = errors
                            if (typeof data !== 'string') {
                                const err12 = {
                                    instancePath,
                                    schemaPath: '#/definitions/ExperimentMetricMathType/type',
                                    keyword: 'type',
                                    params: { type: 'string' },
                                    message: 'must be string',
                                }
                                if (vErrors === null) {
                                    vErrors = [err12]
                                } else {
                                    vErrors.push(err12)
                                }
                                errors++
                            }
                            if (
                                !(
                                    data === 'total' ||
                                    data === 'sum' ||
                                    data === 'unique_session' ||
                                    data === 'min' ||
                                    data === 'max' ||
                                    data === 'avg' ||
                                    data === 'dau' ||
                                    data === 'unique_group' ||
                                    data === 'hogql'
                                )
                            ) {
                                const err13 = {
                                    instancePath,
                                    schemaPath: '#/definitions/ExperimentMetricMathType/enum',
                                    keyword: 'enum',
                                    params: { allowedValues: schema84.enum },
                                    message: 'must be equal to one of the allowed values',
                                }
                                if (vErrors === null) {
                                    vErrors = [err13]
                                } else {
                                    vErrors.push(err13)
                                }
                                errors++
                            }
                            var _valid0 = _errs19 === errors
                            valid0 = valid0 || _valid0
                            if (!valid0) {
                                const _errs22 = errors
                                if (typeof data !== 'string') {
                                    const err14 = {
                                        instancePath,
                                        schemaPath: '#/definitions/CalendarHeatmapMathType/type',
                                        keyword: 'type',
                                        params: { type: 'string' },
                                        message: 'must be string',
                                    }
                                    if (vErrors === null) {
                                        vErrors = [err14]
                                    } else {
                                        vErrors.push(err14)
                                    }
                                    errors++
                                }
                                if (!(data === 'total' || data === 'dau')) {
                                    const err15 = {
                                        instancePath,
                                        schemaPath: '#/definitions/CalendarHeatmapMathType/enum',
                                        keyword: 'enum',
                                        params: { allowedValues: schema85.enum },
                                        message: 'must be equal to one of the allowed values',
                                    }
                                    if (vErrors === null) {
                                        vErrors = [err15]
                                    } else {
                                        vErrors.push(err15)
                                    }
                                    errors++
                                }
                                var _valid0 = _errs22 === errors
                                valid0 = valid0 || _valid0
                            }
                        }
                    }
                }
            }
        }
    }
    if (!valid0) {
        const err16 = {
            instancePath,
            schemaPath: '#/anyOf',
            keyword: 'anyOf',
            params: {},
            message: 'must match a schema in anyOf',
        }
        if (vErrors === null) {
            vErrors = [err16]
        } else {
            vErrors.push(err16)
        }
        errors++
        validate81.errors = vErrors
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
    validate81.errors = vErrors
    return errors === 0
}
const schema86 = {
    additionalProperties: false,
    properties: { property: { type: 'string' }, static: { $ref: '#/definitions/CurrencyCode' } },
    type: 'object',
}
const schema87 = {
    enum: [
        'AED',
        'AFN',
        'ALL',
        'AMD',
        'ANG',
        'AOA',
        'ARS',
        'AUD',
        'AWG',
        'AZN',
        'BAM',
        'BBD',
        'BDT',
        'BGN',
        'BHD',
        'BIF',
        'BMD',
        'BND',
        'BOB',
        'BRL',
        'BSD',
        'BTC',
        'BTN',
        'BWP',
        'BYN',
        'BZD',
        'CAD',
        'CDF',
        'CHF',
        'CLP',
        'CNY',
        'COP',
        'CRC',
        'CVE',
        'CZK',
        'DJF',
        'DKK',
        'DOP',
        'DZD',
        'EGP',
        'ERN',
        'ETB',
        'EUR',
        'FJD',
        'GBP',
        'GEL',
        'GHS',
        'GIP',
        'GMD',
        'GNF',
        'GTQ',
        'GYD',
        'HKD',
        'HNL',
        'HRK',
        'HTG',
        'HUF',
        'IDR',
        'ILS',
        'INR',
        'IQD',
        'IRR',
        'ISK',
        'JMD',
        'JOD',
        'JPY',
        'KES',
        'KGS',
        'KHR',
        'KMF',
        'KRW',
        'KWD',
        'KYD',
        'KZT',
        'LAK',
        'LBP',
        'LKR',
        'LRD',
        'LTL',
        'LVL',
        'LSL',
        'LYD',
        'MAD',
        'MDL',
        'MGA',
        'MKD',
        'MMK',
        'MNT',
        'MOP',
        'MRU',
        'MTL',
        'MUR',
        'MVR',
        'MWK',
        'MXN',
        'MYR',
        'MZN',
        'NAD',
        'NGN',
        'NIO',
        'NOK',
        'NPR',
        'NZD',
        'OMR',
        'PAB',
        'PEN',
        'PGK',
        'PHP',
        'PKR',
        'PLN',
        'PYG',
        'QAR',
        'RON',
        'RSD',
        'RUB',
        'RWF',
        'SAR',
        'SBD',
        'SCR',
        'SDG',
        'SEK',
        'SGD',
        'SRD',
        'SSP',
        'STN',
        'SYP',
        'SZL',
        'THB',
        'TJS',
        'TMT',
        'TND',
        'TOP',
        'TRY',
        'TTD',
        'TWD',
        'TZS',
        'UAH',
        'UGX',
        'USD',
        'UYU',
        'UZS',
        'VES',
        'VND',
        'VUV',
        'WST',
        'XAF',
        'XCD',
        'XOF',
        'XPF',
        'YER',
        'ZAR',
        'ZMW',
    ],
    type: 'string',
}
function validate83(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            const _errs1 = errors
            for (const key0 in data) {
                if (!(key0 === 'property' || key0 === 'static')) {
                    validate83.errors = [
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
                if (data.property !== undefined) {
                    const _errs2 = errors
                    if (typeof data.property !== 'string') {
                        validate83.errors = [
                            {
                                instancePath: instancePath + '/property',
                                schemaPath: '#/properties/property/type',
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
                    if (data.static !== undefined) {
                        let data1 = data.static
                        const _errs4 = errors
                        if (typeof data1 !== 'string') {
                            validate83.errors = [
                                {
                                    instancePath: instancePath + '/static',
                                    schemaPath: '#/definitions/CurrencyCode/type',
                                    keyword: 'type',
                                    params: { type: 'string' },
                                    message: 'must be string',
                                },
                            ]
                            return false
                        }
                        if (
                            !(
                                data1 === 'AED' ||
                                data1 === 'AFN' ||
                                data1 === 'ALL' ||
                                data1 === 'AMD' ||
                                data1 === 'ANG' ||
                                data1 === 'AOA' ||
                                data1 === 'ARS' ||
                                data1 === 'AUD' ||
                                data1 === 'AWG' ||
                                data1 === 'AZN' ||
                                data1 === 'BAM' ||
                                data1 === 'BBD' ||
                                data1 === 'BDT' ||
                                data1 === 'BGN' ||
                                data1 === 'BHD' ||
                                data1 === 'BIF' ||
                                data1 === 'BMD' ||
                                data1 === 'BND' ||
                                data1 === 'BOB' ||
                                data1 === 'BRL' ||
                                data1 === 'BSD' ||
                                data1 === 'BTC' ||
                                data1 === 'BTN' ||
                                data1 === 'BWP' ||
                                data1 === 'BYN' ||
                                data1 === 'BZD' ||
                                data1 === 'CAD' ||
                                data1 === 'CDF' ||
                                data1 === 'CHF' ||
                                data1 === 'CLP' ||
                                data1 === 'CNY' ||
                                data1 === 'COP' ||
                                data1 === 'CRC' ||
                                data1 === 'CVE' ||
                                data1 === 'CZK' ||
                                data1 === 'DJF' ||
                                data1 === 'DKK' ||
                                data1 === 'DOP' ||
                                data1 === 'DZD' ||
                                data1 === 'EGP' ||
                                data1 === 'ERN' ||
                                data1 === 'ETB' ||
                                data1 === 'EUR' ||
                                data1 === 'FJD' ||
                                data1 === 'GBP' ||
                                data1 === 'GEL' ||
                                data1 === 'GHS' ||
                                data1 === 'GIP' ||
                                data1 === 'GMD' ||
                                data1 === 'GNF' ||
                                data1 === 'GTQ' ||
                                data1 === 'GYD' ||
                                data1 === 'HKD' ||
                                data1 === 'HNL' ||
                                data1 === 'HRK' ||
                                data1 === 'HTG' ||
                                data1 === 'HUF' ||
                                data1 === 'IDR' ||
                                data1 === 'ILS' ||
                                data1 === 'INR' ||
                                data1 === 'IQD' ||
                                data1 === 'IRR' ||
                                data1 === 'ISK' ||
                                data1 === 'JMD' ||
                                data1 === 'JOD' ||
                                data1 === 'JPY' ||
                                data1 === 'KES' ||
                                data1 === 'KGS' ||
                                data1 === 'KHR' ||
                                data1 === 'KMF' ||
                                data1 === 'KRW' ||
                                data1 === 'KWD' ||
                                data1 === 'KYD' ||
                                data1 === 'KZT' ||
                                data1 === 'LAK' ||
                                data1 === 'LBP' ||
                                data1 === 'LKR' ||
                                data1 === 'LRD' ||
                                data1 === 'LTL' ||
                                data1 === 'LVL' ||
                                data1 === 'LSL' ||
                                data1 === 'LYD' ||
                                data1 === 'MAD' ||
                                data1 === 'MDL' ||
                                data1 === 'MGA' ||
                                data1 === 'MKD' ||
                                data1 === 'MMK' ||
                                data1 === 'MNT' ||
                                data1 === 'MOP' ||
                                data1 === 'MRU' ||
                                data1 === 'MTL' ||
                                data1 === 'MUR' ||
                                data1 === 'MVR' ||
                                data1 === 'MWK' ||
                                data1 === 'MXN' ||
                                data1 === 'MYR' ||
                                data1 === 'MZN' ||
                                data1 === 'NAD' ||
                                data1 === 'NGN' ||
                                data1 === 'NIO' ||
                                data1 === 'NOK' ||
                                data1 === 'NPR' ||
                                data1 === 'NZD' ||
                                data1 === 'OMR' ||
                                data1 === 'PAB' ||
                                data1 === 'PEN' ||
                                data1 === 'PGK' ||
                                data1 === 'PHP' ||
                                data1 === 'PKR' ||
                                data1 === 'PLN' ||
                                data1 === 'PYG' ||
                                data1 === 'QAR' ||
                                data1 === 'RON' ||
                                data1 === 'RSD' ||
                                data1 === 'RUB' ||
                                data1 === 'RWF' ||
                                data1 === 'SAR' ||
                                data1 === 'SBD' ||
                                data1 === 'SCR' ||
                                data1 === 'SDG' ||
                                data1 === 'SEK' ||
                                data1 === 'SGD' ||
                                data1 === 'SRD' ||
                                data1 === 'SSP' ||
                                data1 === 'STN' ||
                                data1 === 'SYP' ||
                                data1 === 'SZL' ||
                                data1 === 'THB' ||
                                data1 === 'TJS' ||
                                data1 === 'TMT' ||
                                data1 === 'TND' ||
                                data1 === 'TOP' ||
                                data1 === 'TRY' ||
                                data1 === 'TTD' ||
                                data1 === 'TWD' ||
                                data1 === 'TZS' ||
                                data1 === 'UAH' ||
                                data1 === 'UGX' ||
                                data1 === 'USD' ||
                                data1 === 'UYU' ||
                                data1 === 'UZS' ||
                                data1 === 'VES' ||
                                data1 === 'VND' ||
                                data1 === 'VUV' ||
                                data1 === 'WST' ||
                                data1 === 'XAF' ||
                                data1 === 'XCD' ||
                                data1 === 'XOF' ||
                                data1 === 'XPF' ||
                                data1 === 'YER' ||
                                data1 === 'ZAR' ||
                                data1 === 'ZMW'
                            )
                        ) {
                            validate83.errors = [
                                {
                                    instancePath: instancePath + '/static',
                                    schemaPath: '#/definitions/CurrencyCode/enum',
                                    keyword: 'enum',
                                    params: { allowedValues: schema87.enum },
                                    message: 'must be equal to one of the allowed values',
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
            validate83.errors = [
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
    validate83.errors = vErrors
    return errors === 0
}
function validate79(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if (data.kind === undefined && (missing0 = 'kind')) {
                validate79.errors = [
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
                    if (!func2.call(schema75.properties, key0)) {
                        validate79.errors = [
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
                    if (data.custom_name !== undefined) {
                        const _errs2 = errors
                        if (typeof data.custom_name !== 'string') {
                            validate79.errors = [
                                {
                                    instancePath: instancePath + '/custom_name',
                                    schemaPath: '#/properties/custom_name/type',
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
                        if (data.event !== undefined) {
                            let data1 = data.event
                            const _errs4 = errors
                            if (typeof data1 !== 'string' && data1 !== null) {
                                validate79.errors = [
                                    {
                                        instancePath: instancePath + '/event',
                                        schemaPath: '#/properties/event/type',
                                        keyword: 'type',
                                        params: { type: schema75.properties.event.type },
                                        message: 'must be string,null',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs4 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.fixedProperties !== undefined) {
                                let data2 = data.fixedProperties
                                const _errs6 = errors
                                if (errors === _errs6) {
                                    if (Array.isArray(data2)) {
                                        var valid1 = true
                                        const len0 = data2.length
                                        for (let i0 = 0; i0 < len0; i0++) {
                                            const _errs8 = errors
                                            if (
                                                !validate11(data2[i0], {
                                                    instancePath: instancePath + '/fixedProperties/' + i0,
                                                    parentData: data2,
                                                    parentDataProperty: i0,
                                                    rootData,
                                                })
                                            ) {
                                                vErrors =
                                                    vErrors === null
                                                        ? validate11.errors
                                                        : vErrors.concat(validate11.errors)
                                                errors = vErrors.length
                                            }
                                            var valid1 = _errs8 === errors
                                            if (!valid1) {
                                                break
                                            }
                                        }
                                    } else {
                                        validate79.errors = [
                                            {
                                                instancePath: instancePath + '/fixedProperties',
                                                schemaPath: '#/properties/fixedProperties/type',
                                                keyword: 'type',
                                                params: { type: 'array' },
                                                message: 'must be array',
                                            },
                                        ]
                                        return false
                                    }
                                }
                                var valid0 = _errs6 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.kind !== undefined) {
                                    let data4 = data.kind
                                    const _errs9 = errors
                                    if (typeof data4 !== 'string') {
                                        validate79.errors = [
                                            {
                                                instancePath: instancePath + '/kind',
                                                schemaPath: '#/properties/kind/type',
                                                keyword: 'type',
                                                params: { type: 'string' },
                                                message: 'must be string',
                                            },
                                        ]
                                        return false
                                    }
                                    if ('EventsNode' !== data4) {
                                        validate79.errors = [
                                            {
                                                instancePath: instancePath + '/kind',
                                                schemaPath: '#/properties/kind/const',
                                                keyword: 'const',
                                                params: { allowedValue: 'EventsNode' },
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
                                    if (data.limit !== undefined) {
                                        let data5 = data.limit
                                        const _errs11 = errors
                                        if (
                                            !(
                                                typeof data5 == 'number' &&
                                                !(data5 % 1) &&
                                                !isNaN(data5) &&
                                                isFinite(data5)
                                            )
                                        ) {
                                            validate79.errors = [
                                                {
                                                    instancePath: instancePath + '/limit',
                                                    schemaPath: '#/definitions/integer/type',
                                                    keyword: 'type',
                                                    params: { type: 'integer' },
                                                    message: 'must be integer',
                                                },
                                            ]
                                            return false
                                        }
                                        var valid0 = _errs11 === errors
                                    } else {
                                        var valid0 = true
                                    }
                                    if (valid0) {
                                        if (data.math !== undefined) {
                                            const _errs14 = errors
                                            if (
                                                !validate81(data.math, {
                                                    instancePath: instancePath + '/math',
                                                    parentData: data,
                                                    parentDataProperty: 'math',
                                                    rootData,
                                                })
                                            ) {
                                                vErrors =
                                                    vErrors === null
                                                        ? validate81.errors
                                                        : vErrors.concat(validate81.errors)
                                                errors = vErrors.length
                                            }
                                            var valid0 = _errs14 === errors
                                        } else {
                                            var valid0 = true
                                        }
                                        if (valid0) {
                                            if (data.math_group_type_index !== undefined) {
                                                let data7 = data.math_group_type_index
                                                const _errs15 = errors
                                                if (!(typeof data7 == 'number' && isFinite(data7))) {
                                                    validate79.errors = [
                                                        {
                                                            instancePath: instancePath + '/math_group_type_index',
                                                            schemaPath: '#/properties/math_group_type_index/type',
                                                            keyword: 'type',
                                                            params: { type: 'number' },
                                                            message: 'must be number',
                                                        },
                                                    ]
                                                    return false
                                                }
                                                if (
                                                    !(
                                                        data7 === 0 ||
                                                        data7 === 1 ||
                                                        data7 === 2 ||
                                                        data7 === 3 ||
                                                        data7 === 4
                                                    )
                                                ) {
                                                    validate79.errors = [
                                                        {
                                                            instancePath: instancePath + '/math_group_type_index',
                                                            schemaPath: '#/properties/math_group_type_index/enum',
                                                            keyword: 'enum',
                                                            params: {
                                                                allowedValues:
                                                                    schema75.properties.math_group_type_index.enum,
                                                            },
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
                                                if (data.math_hogql !== undefined) {
                                                    const _errs17 = errors
                                                    if (typeof data.math_hogql !== 'string') {
                                                        validate79.errors = [
                                                            {
                                                                instancePath: instancePath + '/math_hogql',
                                                                schemaPath: '#/properties/math_hogql/type',
                                                                keyword: 'type',
                                                                params: { type: 'string' },
                                                                message: 'must be string',
                                                            },
                                                        ]
                                                        return false
                                                    }
                                                    var valid0 = _errs17 === errors
                                                } else {
                                                    var valid0 = true
                                                }
                                                if (valid0) {
                                                    if (data.math_multiplier !== undefined) {
                                                        let data9 = data.math_multiplier
                                                        const _errs19 = errors
                                                        if (!(typeof data9 == 'number' && isFinite(data9))) {
                                                            validate79.errors = [
                                                                {
                                                                    instancePath: instancePath + '/math_multiplier',
                                                                    schemaPath: '#/properties/math_multiplier/type',
                                                                    keyword: 'type',
                                                                    params: { type: 'number' },
                                                                    message: 'must be number',
                                                                },
                                                            ]
                                                            return false
                                                        }
                                                        var valid0 = _errs19 === errors
                                                    } else {
                                                        var valid0 = true
                                                    }
                                                    if (valid0) {
                                                        if (data.math_property !== undefined) {
                                                            const _errs21 = errors
                                                            if (typeof data.math_property !== 'string') {
                                                                validate79.errors = [
                                                                    {
                                                                        instancePath: instancePath + '/math_property',
                                                                        schemaPath: '#/properties/math_property/type',
                                                                        keyword: 'type',
                                                                        params: { type: 'string' },
                                                                        message: 'must be string',
                                                                    },
                                                                ]
                                                                return false
                                                            }
                                                            var valid0 = _errs21 === errors
                                                        } else {
                                                            var valid0 = true
                                                        }
                                                        if (valid0) {
                                                            if (data.math_property_revenue_currency !== undefined) {
                                                                const _errs23 = errors
                                                                if (
                                                                    !validate83(data.math_property_revenue_currency, {
                                                                        instancePath:
                                                                            instancePath +
                                                                            '/math_property_revenue_currency',
                                                                        parentData: data,
                                                                        parentDataProperty:
                                                                            'math_property_revenue_currency',
                                                                        rootData,
                                                                    })
                                                                ) {
                                                                    vErrors =
                                                                        vErrors === null
                                                                            ? validate83.errors
                                                                            : vErrors.concat(validate83.errors)
                                                                    errors = vErrors.length
                                                                }
                                                                var valid0 = _errs23 === errors
                                                            } else {
                                                                var valid0 = true
                                                            }
                                                            if (valid0) {
                                                                if (data.math_property_type !== undefined) {
                                                                    const _errs24 = errors
                                                                    if (typeof data.math_property_type !== 'string') {
                                                                        validate79.errors = [
                                                                            {
                                                                                instancePath:
                                                                                    instancePath +
                                                                                    '/math_property_type',
                                                                                schemaPath:
                                                                                    '#/properties/math_property_type/type',
                                                                                keyword: 'type',
                                                                                params: { type: 'string' },
                                                                                message: 'must be string',
                                                                            },
                                                                        ]
                                                                        return false
                                                                    }
                                                                    var valid0 = _errs24 === errors
                                                                } else {
                                                                    var valid0 = true
                                                                }
                                                                if (valid0) {
                                                                    if (data.name !== undefined) {
                                                                        const _errs26 = errors
                                                                        if (typeof data.name !== 'string') {
                                                                            validate79.errors = [
                                                                                {
                                                                                    instancePath:
                                                                                        instancePath + '/name',
                                                                                    schemaPath:
                                                                                        '#/properties/name/type',
                                                                                    keyword: 'type',
                                                                                    params: { type: 'string' },
                                                                                    message: 'must be string',
                                                                                },
                                                                            ]
                                                                            return false
                                                                        }
                                                                        var valid0 = _errs26 === errors
                                                                    } else {
                                                                        var valid0 = true
                                                                    }
                                                                    if (valid0) {
                                                                        if (data.optionalInFunnel !== undefined) {
                                                                            const _errs28 = errors
                                                                            if (
                                                                                typeof data.optionalInFunnel !==
                                                                                'boolean'
                                                                            ) {
                                                                                validate79.errors = [
                                                                                    {
                                                                                        instancePath:
                                                                                            instancePath +
                                                                                            '/optionalInFunnel',
                                                                                        schemaPath:
                                                                                            '#/properties/optionalInFunnel/type',
                                                                                        keyword: 'type',
                                                                                        params: { type: 'boolean' },
                                                                                        message: 'must be boolean',
                                                                                    },
                                                                                ]
                                                                                return false
                                                                            }
                                                                            var valid0 = _errs28 === errors
                                                                        } else {
                                                                            var valid0 = true
                                                                        }
                                                                        if (valid0) {
                                                                            if (data.orderBy !== undefined) {
                                                                                let data15 = data.orderBy
                                                                                const _errs30 = errors
                                                                                if (errors === _errs30) {
                                                                                    if (Array.isArray(data15)) {
                                                                                        var valid3 = true
                                                                                        const len1 = data15.length
                                                                                        for (
                                                                                            let i1 = 0;
                                                                                            i1 < len1;
                                                                                            i1++
                                                                                        ) {
                                                                                            const _errs32 = errors
                                                                                            if (
                                                                                                typeof data15[i1] !==
                                                                                                'string'
                                                                                            ) {
                                                                                                validate79.errors = [
                                                                                                    {
                                                                                                        instancePath:
                                                                                                            instancePath +
                                                                                                            '/orderBy/' +
                                                                                                            i1,
                                                                                                        schemaPath:
                                                                                                            '#/properties/orderBy/items/type',
                                                                                                        keyword: 'type',
                                                                                                        params: {
                                                                                                            type: 'string',
                                                                                                        },
                                                                                                        message:
                                                                                                            'must be string',
                                                                                                    },
                                                                                                ]
                                                                                                return false
                                                                                            }
                                                                                            var valid3 =
                                                                                                _errs32 === errors
                                                                                            if (!valid3) {
                                                                                                break
                                                                                            }
                                                                                        }
                                                                                    } else {
                                                                                        validate79.errors = [
                                                                                            {
                                                                                                instancePath:
                                                                                                    instancePath +
                                                                                                    '/orderBy',
                                                                                                schemaPath:
                                                                                                    '#/properties/orderBy/type',
                                                                                                keyword: 'type',
                                                                                                params: {
                                                                                                    type: 'array',
                                                                                                },
                                                                                                message:
                                                                                                    'must be array',
                                                                                            },
                                                                                        ]
                                                                                        return false
                                                                                    }
                                                                                }
                                                                                var valid0 = _errs30 === errors
                                                                            } else {
                                                                                var valid0 = true
                                                                            }
                                                                            if (valid0) {
                                                                                if (data.properties !== undefined) {
                                                                                    let data17 = data.properties
                                                                                    const _errs34 = errors
                                                                                    if (errors === _errs34) {
                                                                                        if (Array.isArray(data17)) {
                                                                                            var valid4 = true
                                                                                            const len2 = data17.length
                                                                                            for (
                                                                                                let i2 = 0;
                                                                                                i2 < len2;
                                                                                                i2++
                                                                                            ) {
                                                                                                const _errs36 = errors
                                                                                                if (
                                                                                                    !validate11(
                                                                                                        data17[i2],
                                                                                                        {
                                                                                                            instancePath:
                                                                                                                instancePath +
                                                                                                                '/properties/' +
                                                                                                                i2,
                                                                                                            parentData:
                                                                                                                data17,
                                                                                                            parentDataProperty:
                                                                                                                i2,
                                                                                                            rootData,
                                                                                                        }
                                                                                                    )
                                                                                                ) {
                                                                                                    vErrors =
                                                                                                        vErrors === null
                                                                                                            ? validate11.errors
                                                                                                            : vErrors.concat(
                                                                                                                  validate11.errors
                                                                                                              )
                                                                                                    errors =
                                                                                                        vErrors.length
                                                                                                }
                                                                                                var valid4 =
                                                                                                    _errs36 === errors
                                                                                                if (!valid4) {
                                                                                                    break
                                                                                                }
                                                                                            }
                                                                                        } else {
                                                                                            validate79.errors = [
                                                                                                {
                                                                                                    instancePath:
                                                                                                        instancePath +
                                                                                                        '/properties',
                                                                                                    schemaPath:
                                                                                                        '#/properties/properties/type',
                                                                                                    keyword: 'type',
                                                                                                    params: {
                                                                                                        type: 'array',
                                                                                                    },
                                                                                                    message:
                                                                                                        'must be array',
                                                                                                },
                                                                                            ]
                                                                                            return false
                                                                                        }
                                                                                    }
                                                                                    var valid0 = _errs34 === errors
                                                                                } else {
                                                                                    var valid0 = true
                                                                                }
                                                                                if (valid0) {
                                                                                    if (data.response !== undefined) {
                                                                                        let data19 = data.response
                                                                                        const _errs37 = errors
                                                                                        if (
                                                                                            !(
                                                                                                data19 &&
                                                                                                typeof data19 ==
                                                                                                    'object' &&
                                                                                                !Array.isArray(data19)
                                                                                            )
                                                                                        ) {
                                                                                            validate79.errors = [
                                                                                                {
                                                                                                    instancePath:
                                                                                                        instancePath +
                                                                                                        '/response',
                                                                                                    schemaPath:
                                                                                                        '#/properties/response/type',
                                                                                                    keyword: 'type',
                                                                                                    params: {
                                                                                                        type: 'object',
                                                                                                    },
                                                                                                    message:
                                                                                                        'must be object',
                                                                                                },
                                                                                            ]
                                                                                            return false
                                                                                        }
                                                                                        var valid0 = _errs37 === errors
                                                                                    } else {
                                                                                        var valid0 = true
                                                                                    }
                                                                                    if (valid0) {
                                                                                        if (
                                                                                            data.version !== undefined
                                                                                        ) {
                                                                                            let data20 = data.version
                                                                                            const _errs39 = errors
                                                                                            if (
                                                                                                !(
                                                                                                    typeof data20 ==
                                                                                                        'number' &&
                                                                                                    isFinite(data20)
                                                                                                )
                                                                                            ) {
                                                                                                validate79.errors = [
                                                                                                    {
                                                                                                        instancePath:
                                                                                                            instancePath +
                                                                                                            '/version',
                                                                                                        schemaPath:
                                                                                                            '#/properties/version/type',
                                                                                                        keyword: 'type',
                                                                                                        params: {
                                                                                                            type: 'number',
                                                                                                        },
                                                                                                        message:
                                                                                                            'must be number',
                                                                                                    },
                                                                                                ]
                                                                                                return false
                                                                                            }
                                                                                            var valid0 =
                                                                                                _errs39 === errors
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
            validate79.errors = [
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
    validate79.errors = vErrors
    return errors === 0
}
const schema88 = {
    additionalProperties: false,
    properties: {
        custom_name: { type: 'string' },
        fixedProperties: {
            description:
                "Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
            items: { $ref: '#/definitions/AnyPropertyFilter' },
            type: 'array',
        },
        id: { $ref: '#/definitions/integer' },
        kind: { const: 'ActionsNode', type: 'string' },
        math: { $ref: '#/definitions/MathType' },
        math_group_type_index: { enum: [0, 1, 2, 3, 4], type: 'number' },
        math_hogql: { type: 'string' },
        math_multiplier: { type: 'number' },
        math_property: { type: 'string' },
        math_property_revenue_currency: { $ref: '#/definitions/RevenueCurrencyPropertyConfig' },
        math_property_type: { type: 'string' },
        name: { type: 'string' },
        optionalInFunnel: { type: 'boolean' },
        properties: {
            description: 'Properties configurable in the interface',
            items: { $ref: '#/definitions/AnyPropertyFilter' },
            type: 'array',
        },
        response: { type: 'object' },
        version: { description: 'version of the node, used for schema migrations', type: 'number' },
    },
    required: ['id', 'kind'],
    type: 'object',
}
function validate87(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if ((data.id === undefined && (missing0 = 'id')) || (data.kind === undefined && (missing0 = 'kind'))) {
                validate87.errors = [
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
                    if (!func2.call(schema88.properties, key0)) {
                        validate87.errors = [
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
                    if (data.custom_name !== undefined) {
                        const _errs2 = errors
                        if (typeof data.custom_name !== 'string') {
                            validate87.errors = [
                                {
                                    instancePath: instancePath + '/custom_name',
                                    schemaPath: '#/properties/custom_name/type',
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
                        if (data.fixedProperties !== undefined) {
                            let data1 = data.fixedProperties
                            const _errs4 = errors
                            if (errors === _errs4) {
                                if (Array.isArray(data1)) {
                                    var valid1 = true
                                    const len0 = data1.length
                                    for (let i0 = 0; i0 < len0; i0++) {
                                        const _errs6 = errors
                                        if (
                                            !validate11(data1[i0], {
                                                instancePath: instancePath + '/fixedProperties/' + i0,
                                                parentData: data1,
                                                parentDataProperty: i0,
                                                rootData,
                                            })
                                        ) {
                                            vErrors =
                                                vErrors === null ? validate11.errors : vErrors.concat(validate11.errors)
                                            errors = vErrors.length
                                        }
                                        var valid1 = _errs6 === errors
                                        if (!valid1) {
                                            break
                                        }
                                    }
                                } else {
                                    validate87.errors = [
                                        {
                                            instancePath: instancePath + '/fixedProperties',
                                            schemaPath: '#/properties/fixedProperties/type',
                                            keyword: 'type',
                                            params: { type: 'array' },
                                            message: 'must be array',
                                        },
                                    ]
                                    return false
                                }
                            }
                            var valid0 = _errs4 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.id !== undefined) {
                                let data3 = data.id
                                const _errs7 = errors
                                if (!(typeof data3 == 'number' && !(data3 % 1) && !isNaN(data3) && isFinite(data3))) {
                                    validate87.errors = [
                                        {
                                            instancePath: instancePath + '/id',
                                            schemaPath: '#/definitions/integer/type',
                                            keyword: 'type',
                                            params: { type: 'integer' },
                                            message: 'must be integer',
                                        },
                                    ]
                                    return false
                                }
                                var valid0 = _errs7 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.kind !== undefined) {
                                    let data4 = data.kind
                                    const _errs10 = errors
                                    if (typeof data4 !== 'string') {
                                        validate87.errors = [
                                            {
                                                instancePath: instancePath + '/kind',
                                                schemaPath: '#/properties/kind/type',
                                                keyword: 'type',
                                                params: { type: 'string' },
                                                message: 'must be string',
                                            },
                                        ]
                                        return false
                                    }
                                    if ('ActionsNode' !== data4) {
                                        validate87.errors = [
                                            {
                                                instancePath: instancePath + '/kind',
                                                schemaPath: '#/properties/kind/const',
                                                keyword: 'const',
                                                params: { allowedValue: 'ActionsNode' },
                                                message: 'must be equal to constant',
                                            },
                                        ]
                                        return false
                                    }
                                    var valid0 = _errs10 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.math !== undefined) {
                                        const _errs12 = errors
                                        if (
                                            !validate81(data.math, {
                                                instancePath: instancePath + '/math',
                                                parentData: data,
                                                parentDataProperty: 'math',
                                                rootData,
                                            })
                                        ) {
                                            vErrors =
                                                vErrors === null ? validate81.errors : vErrors.concat(validate81.errors)
                                            errors = vErrors.length
                                        }
                                        var valid0 = _errs12 === errors
                                    } else {
                                        var valid0 = true
                                    }
                                    if (valid0) {
                                        if (data.math_group_type_index !== undefined) {
                                            let data6 = data.math_group_type_index
                                            const _errs13 = errors
                                            if (!(typeof data6 == 'number' && isFinite(data6))) {
                                                validate87.errors = [
                                                    {
                                                        instancePath: instancePath + '/math_group_type_index',
                                                        schemaPath: '#/properties/math_group_type_index/type',
                                                        keyword: 'type',
                                                        params: { type: 'number' },
                                                        message: 'must be number',
                                                    },
                                                ]
                                                return false
                                            }
                                            if (
                                                !(
                                                    data6 === 0 ||
                                                    data6 === 1 ||
                                                    data6 === 2 ||
                                                    data6 === 3 ||
                                                    data6 === 4
                                                )
                                            ) {
                                                validate87.errors = [
                                                    {
                                                        instancePath: instancePath + '/math_group_type_index',
                                                        schemaPath: '#/properties/math_group_type_index/enum',
                                                        keyword: 'enum',
                                                        params: {
                                                            allowedValues:
                                                                schema88.properties.math_group_type_index.enum,
                                                        },
                                                        message: 'must be equal to one of the allowed values',
                                                    },
                                                ]
                                                return false
                                            }
                                            var valid0 = _errs13 === errors
                                        } else {
                                            var valid0 = true
                                        }
                                        if (valid0) {
                                            if (data.math_hogql !== undefined) {
                                                const _errs15 = errors
                                                if (typeof data.math_hogql !== 'string') {
                                                    validate87.errors = [
                                                        {
                                                            instancePath: instancePath + '/math_hogql',
                                                            schemaPath: '#/properties/math_hogql/type',
                                                            keyword: 'type',
                                                            params: { type: 'string' },
                                                            message: 'must be string',
                                                        },
                                                    ]
                                                    return false
                                                }
                                                var valid0 = _errs15 === errors
                                            } else {
                                                var valid0 = true
                                            }
                                            if (valid0) {
                                                if (data.math_multiplier !== undefined) {
                                                    let data8 = data.math_multiplier
                                                    const _errs17 = errors
                                                    if (!(typeof data8 == 'number' && isFinite(data8))) {
                                                        validate87.errors = [
                                                            {
                                                                instancePath: instancePath + '/math_multiplier',
                                                                schemaPath: '#/properties/math_multiplier/type',
                                                                keyword: 'type',
                                                                params: { type: 'number' },
                                                                message: 'must be number',
                                                            },
                                                        ]
                                                        return false
                                                    }
                                                    var valid0 = _errs17 === errors
                                                } else {
                                                    var valid0 = true
                                                }
                                                if (valid0) {
                                                    if (data.math_property !== undefined) {
                                                        const _errs19 = errors
                                                        if (typeof data.math_property !== 'string') {
                                                            validate87.errors = [
                                                                {
                                                                    instancePath: instancePath + '/math_property',
                                                                    schemaPath: '#/properties/math_property/type',
                                                                    keyword: 'type',
                                                                    params: { type: 'string' },
                                                                    message: 'must be string',
                                                                },
                                                            ]
                                                            return false
                                                        }
                                                        var valid0 = _errs19 === errors
                                                    } else {
                                                        var valid0 = true
                                                    }
                                                    if (valid0) {
                                                        if (data.math_property_revenue_currency !== undefined) {
                                                            const _errs21 = errors
                                                            if (
                                                                !validate83(data.math_property_revenue_currency, {
                                                                    instancePath:
                                                                        instancePath +
                                                                        '/math_property_revenue_currency',
                                                                    parentData: data,
                                                                    parentDataProperty:
                                                                        'math_property_revenue_currency',
                                                                    rootData,
                                                                })
                                                            ) {
                                                                vErrors =
                                                                    vErrors === null
                                                                        ? validate83.errors
                                                                        : vErrors.concat(validate83.errors)
                                                                errors = vErrors.length
                                                            }
                                                            var valid0 = _errs21 === errors
                                                        } else {
                                                            var valid0 = true
                                                        }
                                                        if (valid0) {
                                                            if (data.math_property_type !== undefined) {
                                                                const _errs22 = errors
                                                                if (typeof data.math_property_type !== 'string') {
                                                                    validate87.errors = [
                                                                        {
                                                                            instancePath:
                                                                                instancePath + '/math_property_type',
                                                                            schemaPath:
                                                                                '#/properties/math_property_type/type',
                                                                            keyword: 'type',
                                                                            params: { type: 'string' },
                                                                            message: 'must be string',
                                                                        },
                                                                    ]
                                                                    return false
                                                                }
                                                                var valid0 = _errs22 === errors
                                                            } else {
                                                                var valid0 = true
                                                            }
                                                            if (valid0) {
                                                                if (data.name !== undefined) {
                                                                    const _errs24 = errors
                                                                    if (typeof data.name !== 'string') {
                                                                        validate87.errors = [
                                                                            {
                                                                                instancePath: instancePath + '/name',
                                                                                schemaPath: '#/properties/name/type',
                                                                                keyword: 'type',
                                                                                params: { type: 'string' },
                                                                                message: 'must be string',
                                                                            },
                                                                        ]
                                                                        return false
                                                                    }
                                                                    var valid0 = _errs24 === errors
                                                                } else {
                                                                    var valid0 = true
                                                                }
                                                                if (valid0) {
                                                                    if (data.optionalInFunnel !== undefined) {
                                                                        const _errs26 = errors
                                                                        if (
                                                                            typeof data.optionalInFunnel !== 'boolean'
                                                                        ) {
                                                                            validate87.errors = [
                                                                                {
                                                                                    instancePath:
                                                                                        instancePath +
                                                                                        '/optionalInFunnel',
                                                                                    schemaPath:
                                                                                        '#/properties/optionalInFunnel/type',
                                                                                    keyword: 'type',
                                                                                    params: { type: 'boolean' },
                                                                                    message: 'must be boolean',
                                                                                },
                                                                            ]
                                                                            return false
                                                                        }
                                                                        var valid0 = _errs26 === errors
                                                                    } else {
                                                                        var valid0 = true
                                                                    }
                                                                    if (valid0) {
                                                                        if (data.properties !== undefined) {
                                                                            let data14 = data.properties
                                                                            const _errs28 = errors
                                                                            if (errors === _errs28) {
                                                                                if (Array.isArray(data14)) {
                                                                                    var valid3 = true
                                                                                    const len1 = data14.length
                                                                                    for (let i1 = 0; i1 < len1; i1++) {
                                                                                        const _errs30 = errors
                                                                                        if (
                                                                                            !validate11(data14[i1], {
                                                                                                instancePath:
                                                                                                    instancePath +
                                                                                                    '/properties/' +
                                                                                                    i1,
                                                                                                parentData: data14,
                                                                                                parentDataProperty: i1,
                                                                                                rootData,
                                                                                            })
                                                                                        ) {
                                                                                            vErrors =
                                                                                                vErrors === null
                                                                                                    ? validate11.errors
                                                                                                    : vErrors.concat(
                                                                                                          validate11.errors
                                                                                                      )
                                                                                            errors = vErrors.length
                                                                                        }
                                                                                        var valid3 = _errs30 === errors
                                                                                        if (!valid3) {
                                                                                            break
                                                                                        }
                                                                                    }
                                                                                } else {
                                                                                    validate87.errors = [
                                                                                        {
                                                                                            instancePath:
                                                                                                instancePath +
                                                                                                '/properties',
                                                                                            schemaPath:
                                                                                                '#/properties/properties/type',
                                                                                            keyword: 'type',
                                                                                            params: { type: 'array' },
                                                                                            message: 'must be array',
                                                                                        },
                                                                                    ]
                                                                                    return false
                                                                                }
                                                                            }
                                                                            var valid0 = _errs28 === errors
                                                                        } else {
                                                                            var valid0 = true
                                                                        }
                                                                        if (valid0) {
                                                                            if (data.response !== undefined) {
                                                                                let data16 = data.response
                                                                                const _errs31 = errors
                                                                                if (
                                                                                    !(
                                                                                        data16 &&
                                                                                        typeof data16 == 'object' &&
                                                                                        !Array.isArray(data16)
                                                                                    )
                                                                                ) {
                                                                                    validate87.errors = [
                                                                                        {
                                                                                            instancePath:
                                                                                                instancePath +
                                                                                                '/response',
                                                                                            schemaPath:
                                                                                                '#/properties/response/type',
                                                                                            keyword: 'type',
                                                                                            params: { type: 'object' },
                                                                                            message: 'must be object',
                                                                                        },
                                                                                    ]
                                                                                    return false
                                                                                }
                                                                                var valid0 = _errs31 === errors
                                                                            } else {
                                                                                var valid0 = true
                                                                            }
                                                                            if (valid0) {
                                                                                if (data.version !== undefined) {
                                                                                    let data17 = data.version
                                                                                    const _errs33 = errors
                                                                                    if (
                                                                                        !(
                                                                                            typeof data17 == 'number' &&
                                                                                            isFinite(data17)
                                                                                        )
                                                                                    ) {
                                                                                        validate87.errors = [
                                                                                            {
                                                                                                instancePath:
                                                                                                    instancePath +
                                                                                                    '/version',
                                                                                                schemaPath:
                                                                                                    '#/properties/version/type',
                                                                                                keyword: 'type',
                                                                                                params: {
                                                                                                    type: 'number',
                                                                                                },
                                                                                                message:
                                                                                                    'must be number',
                                                                                            },
                                                                                        ]
                                                                                        return false
                                                                                    }
                                                                                    var valid0 = _errs33 === errors
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
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } else {
            validate87.errors = [
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
    validate87.errors = vErrors
    return errors === 0
}
const schema90 = {
    additionalProperties: false,
    properties: {
        custom_name: { type: 'string' },
        data_warehouse_join_key: { type: 'string' },
        events_join_key: { type: 'string' },
        fixedProperties: {
            description:
                "Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
            items: { $ref: '#/definitions/AnyPropertyFilter' },
            type: 'array',
        },
        kind: { const: 'ExperimentDataWarehouseNode', type: 'string' },
        math: { $ref: '#/definitions/MathType' },
        math_group_type_index: { enum: [0, 1, 2, 3, 4], type: 'number' },
        math_hogql: { type: 'string' },
        math_multiplier: { type: 'number' },
        math_property: { type: 'string' },
        math_property_revenue_currency: { $ref: '#/definitions/RevenueCurrencyPropertyConfig' },
        math_property_type: { type: 'string' },
        name: { type: 'string' },
        optionalInFunnel: { type: 'boolean' },
        properties: {
            description: 'Properties configurable in the interface',
            items: { $ref: '#/definitions/AnyPropertyFilter' },
            type: 'array',
        },
        response: { type: 'object' },
        table_name: { type: 'string' },
        timestamp_field: { type: 'string' },
        version: { description: 'version of the node, used for schema migrations', type: 'number' },
    },
    required: ['data_warehouse_join_key', 'events_join_key', 'kind', 'table_name', 'timestamp_field'],
    type: 'object',
}
function validate93(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if (
                (data.data_warehouse_join_key === undefined && (missing0 = 'data_warehouse_join_key')) ||
                (data.events_join_key === undefined && (missing0 = 'events_join_key')) ||
                (data.kind === undefined && (missing0 = 'kind')) ||
                (data.table_name === undefined && (missing0 = 'table_name')) ||
                (data.timestamp_field === undefined && (missing0 = 'timestamp_field'))
            ) {
                validate93.errors = [
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
                    if (!func2.call(schema90.properties, key0)) {
                        validate93.errors = [
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
                    if (data.custom_name !== undefined) {
                        const _errs2 = errors
                        if (typeof data.custom_name !== 'string') {
                            validate93.errors = [
                                {
                                    instancePath: instancePath + '/custom_name',
                                    schemaPath: '#/properties/custom_name/type',
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
                        if (data.data_warehouse_join_key !== undefined) {
                            const _errs4 = errors
                            if (typeof data.data_warehouse_join_key !== 'string') {
                                validate93.errors = [
                                    {
                                        instancePath: instancePath + '/data_warehouse_join_key',
                                        schemaPath: '#/properties/data_warehouse_join_key/type',
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
                            if (data.events_join_key !== undefined) {
                                const _errs6 = errors
                                if (typeof data.events_join_key !== 'string') {
                                    validate93.errors = [
                                        {
                                            instancePath: instancePath + '/events_join_key',
                                            schemaPath: '#/properties/events_join_key/type',
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
                                if (data.fixedProperties !== undefined) {
                                    let data3 = data.fixedProperties
                                    const _errs8 = errors
                                    if (errors === _errs8) {
                                        if (Array.isArray(data3)) {
                                            var valid1 = true
                                            const len0 = data3.length
                                            for (let i0 = 0; i0 < len0; i0++) {
                                                const _errs10 = errors
                                                if (
                                                    !validate11(data3[i0], {
                                                        instancePath: instancePath + '/fixedProperties/' + i0,
                                                        parentData: data3,
                                                        parentDataProperty: i0,
                                                        rootData,
                                                    })
                                                ) {
                                                    vErrors =
                                                        vErrors === null
                                                            ? validate11.errors
                                                            : vErrors.concat(validate11.errors)
                                                    errors = vErrors.length
                                                }
                                                var valid1 = _errs10 === errors
                                                if (!valid1) {
                                                    break
                                                }
                                            }
                                        } else {
                                            validate93.errors = [
                                                {
                                                    instancePath: instancePath + '/fixedProperties',
                                                    schemaPath: '#/properties/fixedProperties/type',
                                                    keyword: 'type',
                                                    params: { type: 'array' },
                                                    message: 'must be array',
                                                },
                                            ]
                                            return false
                                        }
                                    }
                                    var valid0 = _errs8 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.kind !== undefined) {
                                        let data5 = data.kind
                                        const _errs11 = errors
                                        if (typeof data5 !== 'string') {
                                            validate93.errors = [
                                                {
                                                    instancePath: instancePath + '/kind',
                                                    schemaPath: '#/properties/kind/type',
                                                    keyword: 'type',
                                                    params: { type: 'string' },
                                                    message: 'must be string',
                                                },
                                            ]
                                            return false
                                        }
                                        if ('ExperimentDataWarehouseNode' !== data5) {
                                            validate93.errors = [
                                                {
                                                    instancePath: instancePath + '/kind',
                                                    schemaPath: '#/properties/kind/const',
                                                    keyword: 'const',
                                                    params: { allowedValue: 'ExperimentDataWarehouseNode' },
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
                                        if (data.math !== undefined) {
                                            const _errs13 = errors
                                            if (
                                                !validate81(data.math, {
                                                    instancePath: instancePath + '/math',
                                                    parentData: data,
                                                    parentDataProperty: 'math',
                                                    rootData,
                                                })
                                            ) {
                                                vErrors =
                                                    vErrors === null
                                                        ? validate81.errors
                                                        : vErrors.concat(validate81.errors)
                                                errors = vErrors.length
                                            }
                                            var valid0 = _errs13 === errors
                                        } else {
                                            var valid0 = true
                                        }
                                        if (valid0) {
                                            if (data.math_group_type_index !== undefined) {
                                                let data7 = data.math_group_type_index
                                                const _errs14 = errors
                                                if (!(typeof data7 == 'number' && isFinite(data7))) {
                                                    validate93.errors = [
                                                        {
                                                            instancePath: instancePath + '/math_group_type_index',
                                                            schemaPath: '#/properties/math_group_type_index/type',
                                                            keyword: 'type',
                                                            params: { type: 'number' },
                                                            message: 'must be number',
                                                        },
                                                    ]
                                                    return false
                                                }
                                                if (
                                                    !(
                                                        data7 === 0 ||
                                                        data7 === 1 ||
                                                        data7 === 2 ||
                                                        data7 === 3 ||
                                                        data7 === 4
                                                    )
                                                ) {
                                                    validate93.errors = [
                                                        {
                                                            instancePath: instancePath + '/math_group_type_index',
                                                            schemaPath: '#/properties/math_group_type_index/enum',
                                                            keyword: 'enum',
                                                            params: {
                                                                allowedValues:
                                                                    schema90.properties.math_group_type_index.enum,
                                                            },
                                                            message: 'must be equal to one of the allowed values',
                                                        },
                                                    ]
                                                    return false
                                                }
                                                var valid0 = _errs14 === errors
                                            } else {
                                                var valid0 = true
                                            }
                                            if (valid0) {
                                                if (data.math_hogql !== undefined) {
                                                    const _errs16 = errors
                                                    if (typeof data.math_hogql !== 'string') {
                                                        validate93.errors = [
                                                            {
                                                                instancePath: instancePath + '/math_hogql',
                                                                schemaPath: '#/properties/math_hogql/type',
                                                                keyword: 'type',
                                                                params: { type: 'string' },
                                                                message: 'must be string',
                                                            },
                                                        ]
                                                        return false
                                                    }
                                                    var valid0 = _errs16 === errors
                                                } else {
                                                    var valid0 = true
                                                }
                                                if (valid0) {
                                                    if (data.math_multiplier !== undefined) {
                                                        let data9 = data.math_multiplier
                                                        const _errs18 = errors
                                                        if (!(typeof data9 == 'number' && isFinite(data9))) {
                                                            validate93.errors = [
                                                                {
                                                                    instancePath: instancePath + '/math_multiplier',
                                                                    schemaPath: '#/properties/math_multiplier/type',
                                                                    keyword: 'type',
                                                                    params: { type: 'number' },
                                                                    message: 'must be number',
                                                                },
                                                            ]
                                                            return false
                                                        }
                                                        var valid0 = _errs18 === errors
                                                    } else {
                                                        var valid0 = true
                                                    }
                                                    if (valid0) {
                                                        if (data.math_property !== undefined) {
                                                            const _errs20 = errors
                                                            if (typeof data.math_property !== 'string') {
                                                                validate93.errors = [
                                                                    {
                                                                        instancePath: instancePath + '/math_property',
                                                                        schemaPath: '#/properties/math_property/type',
                                                                        keyword: 'type',
                                                                        params: { type: 'string' },
                                                                        message: 'must be string',
                                                                    },
                                                                ]
                                                                return false
                                                            }
                                                            var valid0 = _errs20 === errors
                                                        } else {
                                                            var valid0 = true
                                                        }
                                                        if (valid0) {
                                                            if (data.math_property_revenue_currency !== undefined) {
                                                                const _errs22 = errors
                                                                if (
                                                                    !validate83(data.math_property_revenue_currency, {
                                                                        instancePath:
                                                                            instancePath +
                                                                            '/math_property_revenue_currency',
                                                                        parentData: data,
                                                                        parentDataProperty:
                                                                            'math_property_revenue_currency',
                                                                        rootData,
                                                                    })
                                                                ) {
                                                                    vErrors =
                                                                        vErrors === null
                                                                            ? validate83.errors
                                                                            : vErrors.concat(validate83.errors)
                                                                    errors = vErrors.length
                                                                }
                                                                var valid0 = _errs22 === errors
                                                            } else {
                                                                var valid0 = true
                                                            }
                                                            if (valid0) {
                                                                if (data.math_property_type !== undefined) {
                                                                    const _errs23 = errors
                                                                    if (typeof data.math_property_type !== 'string') {
                                                                        validate93.errors = [
                                                                            {
                                                                                instancePath:
                                                                                    instancePath +
                                                                                    '/math_property_type',
                                                                                schemaPath:
                                                                                    '#/properties/math_property_type/type',
                                                                                keyword: 'type',
                                                                                params: { type: 'string' },
                                                                                message: 'must be string',
                                                                            },
                                                                        ]
                                                                        return false
                                                                    }
                                                                    var valid0 = _errs23 === errors
                                                                } else {
                                                                    var valid0 = true
                                                                }
                                                                if (valid0) {
                                                                    if (data.name !== undefined) {
                                                                        const _errs25 = errors
                                                                        if (typeof data.name !== 'string') {
                                                                            validate93.errors = [
                                                                                {
                                                                                    instancePath:
                                                                                        instancePath + '/name',
                                                                                    schemaPath:
                                                                                        '#/properties/name/type',
                                                                                    keyword: 'type',
                                                                                    params: { type: 'string' },
                                                                                    message: 'must be string',
                                                                                },
                                                                            ]
                                                                            return false
                                                                        }
                                                                        var valid0 = _errs25 === errors
                                                                    } else {
                                                                        var valid0 = true
                                                                    }
                                                                    if (valid0) {
                                                                        if (data.optionalInFunnel !== undefined) {
                                                                            const _errs27 = errors
                                                                            if (
                                                                                typeof data.optionalInFunnel !==
                                                                                'boolean'
                                                                            ) {
                                                                                validate93.errors = [
                                                                                    {
                                                                                        instancePath:
                                                                                            instancePath +
                                                                                            '/optionalInFunnel',
                                                                                        schemaPath:
                                                                                            '#/properties/optionalInFunnel/type',
                                                                                        keyword: 'type',
                                                                                        params: { type: 'boolean' },
                                                                                        message: 'must be boolean',
                                                                                    },
                                                                                ]
                                                                                return false
                                                                            }
                                                                            var valid0 = _errs27 === errors
                                                                        } else {
                                                                            var valid0 = true
                                                                        }
                                                                        if (valid0) {
                                                                            if (data.properties !== undefined) {
                                                                                let data15 = data.properties
                                                                                const _errs29 = errors
                                                                                if (errors === _errs29) {
                                                                                    if (Array.isArray(data15)) {
                                                                                        var valid2 = true
                                                                                        const len1 = data15.length
                                                                                        for (
                                                                                            let i1 = 0;
                                                                                            i1 < len1;
                                                                                            i1++
                                                                                        ) {
                                                                                            const _errs31 = errors
                                                                                            if (
                                                                                                !validate11(
                                                                                                    data15[i1],
                                                                                                    {
                                                                                                        instancePath:
                                                                                                            instancePath +
                                                                                                            '/properties/' +
                                                                                                            i1,
                                                                                                        parentData:
                                                                                                            data15,
                                                                                                        parentDataProperty:
                                                                                                            i1,
                                                                                                        rootData,
                                                                                                    }
                                                                                                )
                                                                                            ) {
                                                                                                vErrors =
                                                                                                    vErrors === null
                                                                                                        ? validate11.errors
                                                                                                        : vErrors.concat(
                                                                                                              validate11.errors
                                                                                                          )
                                                                                                errors = vErrors.length
                                                                                            }
                                                                                            var valid2 =
                                                                                                _errs31 === errors
                                                                                            if (!valid2) {
                                                                                                break
                                                                                            }
                                                                                        }
                                                                                    } else {
                                                                                        validate93.errors = [
                                                                                            {
                                                                                                instancePath:
                                                                                                    instancePath +
                                                                                                    '/properties',
                                                                                                schemaPath:
                                                                                                    '#/properties/properties/type',
                                                                                                keyword: 'type',
                                                                                                params: {
                                                                                                    type: 'array',
                                                                                                },
                                                                                                message:
                                                                                                    'must be array',
                                                                                            },
                                                                                        ]
                                                                                        return false
                                                                                    }
                                                                                }
                                                                                var valid0 = _errs29 === errors
                                                                            } else {
                                                                                var valid0 = true
                                                                            }
                                                                            if (valid0) {
                                                                                if (data.response !== undefined) {
                                                                                    let data17 = data.response
                                                                                    const _errs32 = errors
                                                                                    if (
                                                                                        !(
                                                                                            data17 &&
                                                                                            typeof data17 == 'object' &&
                                                                                            !Array.isArray(data17)
                                                                                        )
                                                                                    ) {
                                                                                        validate93.errors = [
                                                                                            {
                                                                                                instancePath:
                                                                                                    instancePath +
                                                                                                    '/response',
                                                                                                schemaPath:
                                                                                                    '#/properties/response/type',
                                                                                                keyword: 'type',
                                                                                                params: {
                                                                                                    type: 'object',
                                                                                                },
                                                                                                message:
                                                                                                    'must be object',
                                                                                            },
                                                                                        ]
                                                                                        return false
                                                                                    }
                                                                                    var valid0 = _errs32 === errors
                                                                                } else {
                                                                                    var valid0 = true
                                                                                }
                                                                                if (valid0) {
                                                                                    if (data.table_name !== undefined) {
                                                                                        const _errs34 = errors
                                                                                        if (
                                                                                            typeof data.table_name !==
                                                                                            'string'
                                                                                        ) {
                                                                                            validate93.errors = [
                                                                                                {
                                                                                                    instancePath:
                                                                                                        instancePath +
                                                                                                        '/table_name',
                                                                                                    schemaPath:
                                                                                                        '#/properties/table_name/type',
                                                                                                    keyword: 'type',
                                                                                                    params: {
                                                                                                        type: 'string',
                                                                                                    },
                                                                                                    message:
                                                                                                        'must be string',
                                                                                                },
                                                                                            ]
                                                                                            return false
                                                                                        }
                                                                                        var valid0 = _errs34 === errors
                                                                                    } else {
                                                                                        var valid0 = true
                                                                                    }
                                                                                    if (valid0) {
                                                                                        if (
                                                                                            data.timestamp_field !==
                                                                                            undefined
                                                                                        ) {
                                                                                            const _errs36 = errors
                                                                                            if (
                                                                                                typeof data.timestamp_field !==
                                                                                                'string'
                                                                                            ) {
                                                                                                validate93.errors = [
                                                                                                    {
                                                                                                        instancePath:
                                                                                                            instancePath +
                                                                                                            '/timestamp_field',
                                                                                                        schemaPath:
                                                                                                            '#/properties/timestamp_field/type',
                                                                                                        keyword: 'type',
                                                                                                        params: {
                                                                                                            type: 'string',
                                                                                                        },
                                                                                                        message:
                                                                                                            'must be string',
                                                                                                    },
                                                                                                ]
                                                                                                return false
                                                                                            }
                                                                                            var valid0 =
                                                                                                _errs36 === errors
                                                                                        } else {
                                                                                            var valid0 = true
                                                                                        }
                                                                                        if (valid0) {
                                                                                            if (
                                                                                                data.version !==
                                                                                                undefined
                                                                                            ) {
                                                                                                let data20 =
                                                                                                    data.version
                                                                                                const _errs38 = errors
                                                                                                if (
                                                                                                    !(
                                                                                                        typeof data20 ==
                                                                                                            'number' &&
                                                                                                        isFinite(data20)
                                                                                                    )
                                                                                                ) {
                                                                                                    validate93.errors =
                                                                                                        [
                                                                                                            {
                                                                                                                instancePath:
                                                                                                                    instancePath +
                                                                                                                    '/version',
                                                                                                                schemaPath:
                                                                                                                    '#/properties/version/type',
                                                                                                                keyword:
                                                                                                                    'type',
                                                                                                                params: {
                                                                                                                    type: 'number',
                                                                                                                },
                                                                                                                message:
                                                                                                                    'must be number',
                                                                                                            },
                                                                                                        ]
                                                                                                    return false
                                                                                                }
                                                                                                var valid0 =
                                                                                                    _errs38 === errors
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
        } else {
            validate93.errors = [
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
    validate93.errors = vErrors
    return errors === 0
}
function validate78(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    const _errs0 = errors
    let valid0 = false
    const _errs1 = errors
    if (!validate79(data, { instancePath, parentData, parentDataProperty, rootData })) {
        vErrors = vErrors === null ? validate79.errors : vErrors.concat(validate79.errors)
        errors = vErrors.length
    }
    var _valid0 = _errs1 === errors
    valid0 = valid0 || _valid0
    if (!valid0) {
        const _errs2 = errors
        if (!validate87(data, { instancePath, parentData, parentDataProperty, rootData })) {
            vErrors = vErrors === null ? validate87.errors : vErrors.concat(validate87.errors)
            errors = vErrors.length
        }
        var _valid0 = _errs2 === errors
        valid0 = valid0 || _valid0
        if (!valid0) {
            const _errs3 = errors
            if (!validate93(data, { instancePath, parentData, parentDataProperty, rootData })) {
                vErrors = vErrors === null ? validate93.errors : vErrors.concat(validate93.errors)
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
        validate78.errors = vErrors
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
    validate78.errors = vErrors
    return errors === 0
}
function validate73(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if (
                (data.kind === undefined && (missing0 = 'kind')) ||
                (data.metric_type === undefined && (missing0 = 'metric_type')) ||
                (data.source === undefined && (missing0 = 'source'))
            ) {
                validate73.errors = [
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
                    if (!func2.call(schema58.properties, key0)) {
                        validate73.errors = [
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
                    if (data.breakdownFilter !== undefined) {
                        const _errs2 = errors
                        if (
                            !validate74(data.breakdownFilter, {
                                instancePath: instancePath + '/breakdownFilter',
                                parentData: data,
                                parentDataProperty: 'breakdownFilter',
                                rootData,
                            })
                        ) {
                            vErrors = vErrors === null ? validate74.errors : vErrors.concat(validate74.errors)
                            errors = vErrors.length
                        }
                        var valid0 = _errs2 === errors
                    } else {
                        var valid0 = true
                    }
                    if (valid0) {
                        if (data.conversion_window !== undefined) {
                            let data1 = data.conversion_window
                            const _errs3 = errors
                            if (!(typeof data1 == 'number' && !(data1 % 1) && !isNaN(data1) && isFinite(data1))) {
                                validate73.errors = [
                                    {
                                        instancePath: instancePath + '/conversion_window',
                                        schemaPath: '#/definitions/integer/type',
                                        keyword: 'type',
                                        params: { type: 'integer' },
                                        message: 'must be integer',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs3 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.conversion_window_unit !== undefined) {
                                let data2 = data.conversion_window_unit
                                const _errs6 = errors
                                if (typeof data2 !== 'string') {
                                    validate73.errors = [
                                        {
                                            instancePath: instancePath + '/conversion_window_unit',
                                            schemaPath: '#/definitions/FunnelConversionWindowTimeUnit/type',
                                            keyword: 'type',
                                            params: { type: 'string' },
                                            message: 'must be string',
                                        },
                                    ]
                                    return false
                                }
                                if (
                                    !(
                                        data2 === 'second' ||
                                        data2 === 'minute' ||
                                        data2 === 'hour' ||
                                        data2 === 'day' ||
                                        data2 === 'week' ||
                                        data2 === 'month'
                                    )
                                ) {
                                    validate73.errors = [
                                        {
                                            instancePath: instancePath + '/conversion_window_unit',
                                            schemaPath: '#/definitions/FunnelConversionWindowTimeUnit/enum',
                                            keyword: 'enum',
                                            params: { allowedValues: schema72.enum },
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
                                if (data.fingerprint !== undefined) {
                                    const _errs9 = errors
                                    if (typeof data.fingerprint !== 'string') {
                                        validate73.errors = [
                                            {
                                                instancePath: instancePath + '/fingerprint',
                                                schemaPath: '#/properties/fingerprint/type',
                                                keyword: 'type',
                                                params: { type: 'string' },
                                                message: 'must be string',
                                            },
                                        ]
                                        return false
                                    }
                                    var valid0 = _errs9 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.goal !== undefined) {
                                        let data4 = data.goal
                                        const _errs11 = errors
                                        if (typeof data4 !== 'string') {
                                            validate73.errors = [
                                                {
                                                    instancePath: instancePath + '/goal',
                                                    schemaPath: '#/definitions/ExperimentMetricGoal/type',
                                                    keyword: 'type',
                                                    params: { type: 'string' },
                                                    message: 'must be string',
                                                },
                                            ]
                                            return false
                                        }
                                        if (!(data4 === 'increase' || data4 === 'decrease')) {
                                            validate73.errors = [
                                                {
                                                    instancePath: instancePath + '/goal',
                                                    schemaPath: '#/definitions/ExperimentMetricGoal/enum',
                                                    keyword: 'enum',
                                                    params: { allowedValues: schema73.enum },
                                                    message: 'must be equal to one of the allowed values',
                                                },
                                            ]
                                            return false
                                        }
                                        var valid0 = _errs11 === errors
                                    } else {
                                        var valid0 = true
                                    }
                                    if (valid0) {
                                        if (data.ignore_zeros !== undefined) {
                                            const _errs14 = errors
                                            if (typeof data.ignore_zeros !== 'boolean') {
                                                validate73.errors = [
                                                    {
                                                        instancePath: instancePath + '/ignore_zeros',
                                                        schemaPath: '#/properties/ignore_zeros/type',
                                                        keyword: 'type',
                                                        params: { type: 'boolean' },
                                                        message: 'must be boolean',
                                                    },
                                                ]
                                                return false
                                            }
                                            var valid0 = _errs14 === errors
                                        } else {
                                            var valid0 = true
                                        }
                                        if (valid0) {
                                            if (data.isSharedMetric !== undefined) {
                                                const _errs16 = errors
                                                if (typeof data.isSharedMetric !== 'boolean') {
                                                    validate73.errors = [
                                                        {
                                                            instancePath: instancePath + '/isSharedMetric',
                                                            schemaPath: '#/properties/isSharedMetric/type',
                                                            keyword: 'type',
                                                            params: { type: 'boolean' },
                                                            message: 'must be boolean',
                                                        },
                                                    ]
                                                    return false
                                                }
                                                var valid0 = _errs16 === errors
                                            } else {
                                                var valid0 = true
                                            }
                                            if (valid0) {
                                                if (data.kind !== undefined) {
                                                    let data7 = data.kind
                                                    const _errs18 = errors
                                                    if (typeof data7 !== 'string') {
                                                        validate73.errors = [
                                                            {
                                                                instancePath: instancePath + '/kind',
                                                                schemaPath: '#/properties/kind/type',
                                                                keyword: 'type',
                                                                params: { type: 'string' },
                                                                message: 'must be string',
                                                            },
                                                        ]
                                                        return false
                                                    }
                                                    if ('ExperimentMetric' !== data7) {
                                                        validate73.errors = [
                                                            {
                                                                instancePath: instancePath + '/kind',
                                                                schemaPath: '#/properties/kind/const',
                                                                keyword: 'const',
                                                                params: { allowedValue: 'ExperimentMetric' },
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
                                                    if (data.lower_bound_percentile !== undefined) {
                                                        let data8 = data.lower_bound_percentile
                                                        const _errs20 = errors
                                                        if (!(typeof data8 == 'number' && isFinite(data8))) {
                                                            validate73.errors = [
                                                                {
                                                                    instancePath:
                                                                        instancePath + '/lower_bound_percentile',
                                                                    schemaPath:
                                                                        '#/properties/lower_bound_percentile/type',
                                                                    keyword: 'type',
                                                                    params: { type: 'number' },
                                                                    message: 'must be number',
                                                                },
                                                            ]
                                                            return false
                                                        }
                                                        var valid0 = _errs20 === errors
                                                    } else {
                                                        var valid0 = true
                                                    }
                                                    if (valid0) {
                                                        if (data.metric_type !== undefined) {
                                                            let data9 = data.metric_type
                                                            const _errs22 = errors
                                                            if (typeof data9 !== 'string') {
                                                                validate73.errors = [
                                                                    {
                                                                        instancePath: instancePath + '/metric_type',
                                                                        schemaPath: '#/properties/metric_type/type',
                                                                        keyword: 'type',
                                                                        params: { type: 'string' },
                                                                        message: 'must be string',
                                                                    },
                                                                ]
                                                                return false
                                                            }
                                                            if ('mean' !== data9) {
                                                                validate73.errors = [
                                                                    {
                                                                        instancePath: instancePath + '/metric_type',
                                                                        schemaPath: '#/properties/metric_type/const',
                                                                        keyword: 'const',
                                                                        params: { allowedValue: 'mean' },
                                                                        message: 'must be equal to constant',
                                                                    },
                                                                ]
                                                                return false
                                                            }
                                                            var valid0 = _errs22 === errors
                                                        } else {
                                                            var valid0 = true
                                                        }
                                                        if (valid0) {
                                                            if (data.name !== undefined) {
                                                                const _errs24 = errors
                                                                if (typeof data.name !== 'string') {
                                                                    validate73.errors = [
                                                                        {
                                                                            instancePath: instancePath + '/name',
                                                                            schemaPath: '#/properties/name/type',
                                                                            keyword: 'type',
                                                                            params: { type: 'string' },
                                                                            message: 'must be string',
                                                                        },
                                                                    ]
                                                                    return false
                                                                }
                                                                var valid0 = _errs24 === errors
                                                            } else {
                                                                var valid0 = true
                                                            }
                                                            if (valid0) {
                                                                if (data.response !== undefined) {
                                                                    let data11 = data.response
                                                                    const _errs26 = errors
                                                                    if (
                                                                        !(
                                                                            data11 &&
                                                                            typeof data11 == 'object' &&
                                                                            !Array.isArray(data11)
                                                                        )
                                                                    ) {
                                                                        validate73.errors = [
                                                                            {
                                                                                instancePath:
                                                                                    instancePath + '/response',
                                                                                schemaPath:
                                                                                    '#/properties/response/type',
                                                                                keyword: 'type',
                                                                                params: { type: 'object' },
                                                                                message: 'must be object',
                                                                            },
                                                                        ]
                                                                        return false
                                                                    }
                                                                    var valid0 = _errs26 === errors
                                                                } else {
                                                                    var valid0 = true
                                                                }
                                                                if (valid0) {
                                                                    if (data.sharedMetricId !== undefined) {
                                                                        let data12 = data.sharedMetricId
                                                                        const _errs28 = errors
                                                                        if (
                                                                            !(
                                                                                typeof data12 == 'number' &&
                                                                                isFinite(data12)
                                                                            )
                                                                        ) {
                                                                            validate73.errors = [
                                                                                {
                                                                                    instancePath:
                                                                                        instancePath +
                                                                                        '/sharedMetricId',
                                                                                    schemaPath:
                                                                                        '#/properties/sharedMetricId/type',
                                                                                    keyword: 'type',
                                                                                    params: { type: 'number' },
                                                                                    message: 'must be number',
                                                                                },
                                                                            ]
                                                                            return false
                                                                        }
                                                                        var valid0 = _errs28 === errors
                                                                    } else {
                                                                        var valid0 = true
                                                                    }
                                                                    if (valid0) {
                                                                        if (data.source !== undefined) {
                                                                            const _errs30 = errors
                                                                            if (
                                                                                !validate78(data.source, {
                                                                                    instancePath:
                                                                                        instancePath + '/source',
                                                                                    parentData: data,
                                                                                    parentDataProperty: 'source',
                                                                                    rootData,
                                                                                })
                                                                            ) {
                                                                                vErrors =
                                                                                    vErrors === null
                                                                                        ? validate78.errors
                                                                                        : vErrors.concat(
                                                                                              validate78.errors
                                                                                          )
                                                                                errors = vErrors.length
                                                                            }
                                                                            var valid0 = _errs30 === errors
                                                                        } else {
                                                                            var valid0 = true
                                                                        }
                                                                        if (valid0) {
                                                                            if (
                                                                                data.upper_bound_percentile !==
                                                                                undefined
                                                                            ) {
                                                                                let data14 = data.upper_bound_percentile
                                                                                const _errs31 = errors
                                                                                if (
                                                                                    !(
                                                                                        typeof data14 == 'number' &&
                                                                                        isFinite(data14)
                                                                                    )
                                                                                ) {
                                                                                    validate73.errors = [
                                                                                        {
                                                                                            instancePath:
                                                                                                instancePath +
                                                                                                '/upper_bound_percentile',
                                                                                            schemaPath:
                                                                                                '#/properties/upper_bound_percentile/type',
                                                                                            keyword: 'type',
                                                                                            params: { type: 'number' },
                                                                                            message: 'must be number',
                                                                                        },
                                                                                    ]
                                                                                    return false
                                                                                }
                                                                                var valid0 = _errs31 === errors
                                                                            } else {
                                                                                var valid0 = true
                                                                            }
                                                                            if (valid0) {
                                                                                if (data.uuid !== undefined) {
                                                                                    const _errs33 = errors
                                                                                    if (typeof data.uuid !== 'string') {
                                                                                        validate73.errors = [
                                                                                            {
                                                                                                instancePath:
                                                                                                    instancePath +
                                                                                                    '/uuid',
                                                                                                schemaPath:
                                                                                                    '#/properties/uuid/type',
                                                                                                keyword: 'type',
                                                                                                params: {
                                                                                                    type: 'string',
                                                                                                },
                                                                                                message:
                                                                                                    'must be string',
                                                                                            },
                                                                                        ]
                                                                                        return false
                                                                                    }
                                                                                    var valid0 = _errs33 === errors
                                                                                } else {
                                                                                    var valid0 = true
                                                                                }
                                                                                if (valid0) {
                                                                                    if (data.version !== undefined) {
                                                                                        let data16 = data.version
                                                                                        const _errs35 = errors
                                                                                        if (
                                                                                            !(
                                                                                                typeof data16 ==
                                                                                                    'number' &&
                                                                                                isFinite(data16)
                                                                                            )
                                                                                        ) {
                                                                                            validate73.errors = [
                                                                                                {
                                                                                                    instancePath:
                                                                                                        instancePath +
                                                                                                        '/version',
                                                                                                    schemaPath:
                                                                                                        '#/properties/version/type',
                                                                                                    keyword: 'type',
                                                                                                    params: {
                                                                                                        type: 'number',
                                                                                                    },
                                                                                                    message:
                                                                                                        'must be number',
                                                                                                },
                                                                                            ]
                                                                                            return false
                                                                                        }
                                                                                        var valid0 = _errs35 === errors
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
            validate73.errors = [
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
    validate73.errors = vErrors
    return errors === 0
}
const schema91 = {
    additionalProperties: false,
    properties: {
        breakdownFilter: { $ref: '#/definitions/BreakdownFilter' },
        conversion_window: { $ref: '#/definitions/integer' },
        conversion_window_unit: { $ref: '#/definitions/FunnelConversionWindowTimeUnit' },
        fingerprint: { type: 'string' },
        funnel_order_type: { $ref: '#/definitions/StepOrderValue' },
        goal: { $ref: '#/definitions/ExperimentMetricGoal' },
        isSharedMetric: { type: 'boolean' },
        kind: { const: 'ExperimentMetric', type: 'string' },
        metric_type: { const: 'funnel', type: 'string' },
        name: { type: 'string' },
        response: { type: 'object' },
        series: { items: { $ref: '#/definitions/ExperimentFunnelMetricStep' }, type: 'array' },
        sharedMetricId: { type: 'number' },
        uuid: { type: 'string' },
        version: { description: 'version of the node, used for schema migrations', type: 'number' },
    },
    required: ['kind', 'metric_type', 'series'],
    type: 'object',
}
const schema94 = { enum: ['strict', 'unordered', 'ordered'], type: 'string' }
const schema96 = { anyOf: [{ $ref: '#/definitions/EventsNode' }, { $ref: '#/definitions/ActionsNode' }] }
function validate103(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    const _errs0 = errors
    let valid0 = false
    const _errs1 = errors
    if (!validate79(data, { instancePath, parentData, parentDataProperty, rootData })) {
        vErrors = vErrors === null ? validate79.errors : vErrors.concat(validate79.errors)
        errors = vErrors.length
    }
    var _valid0 = _errs1 === errors
    valid0 = valid0 || _valid0
    if (!valid0) {
        const _errs2 = errors
        if (!validate87(data, { instancePath, parentData, parentDataProperty, rootData })) {
            vErrors = vErrors === null ? validate87.errors : vErrors.concat(validate87.errors)
            errors = vErrors.length
        }
        var _valid0 = _errs2 === errors
        valid0 = valid0 || _valid0
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
        validate103.errors = vErrors
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
    validate103.errors = vErrors
    return errors === 0
}
function validate101(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if (
                (data.kind === undefined && (missing0 = 'kind')) ||
                (data.metric_type === undefined && (missing0 = 'metric_type')) ||
                (data.series === undefined && (missing0 = 'series'))
            ) {
                validate101.errors = [
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
                    if (!func2.call(schema91.properties, key0)) {
                        validate101.errors = [
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
                    if (data.breakdownFilter !== undefined) {
                        const _errs2 = errors
                        if (
                            !validate74(data.breakdownFilter, {
                                instancePath: instancePath + '/breakdownFilter',
                                parentData: data,
                                parentDataProperty: 'breakdownFilter',
                                rootData,
                            })
                        ) {
                            vErrors = vErrors === null ? validate74.errors : vErrors.concat(validate74.errors)
                            errors = vErrors.length
                        }
                        var valid0 = _errs2 === errors
                    } else {
                        var valid0 = true
                    }
                    if (valid0) {
                        if (data.conversion_window !== undefined) {
                            let data1 = data.conversion_window
                            const _errs3 = errors
                            if (!(typeof data1 == 'number' && !(data1 % 1) && !isNaN(data1) && isFinite(data1))) {
                                validate101.errors = [
                                    {
                                        instancePath: instancePath + '/conversion_window',
                                        schemaPath: '#/definitions/integer/type',
                                        keyword: 'type',
                                        params: { type: 'integer' },
                                        message: 'must be integer',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs3 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.conversion_window_unit !== undefined) {
                                let data2 = data.conversion_window_unit
                                const _errs6 = errors
                                if (typeof data2 !== 'string') {
                                    validate101.errors = [
                                        {
                                            instancePath: instancePath + '/conversion_window_unit',
                                            schemaPath: '#/definitions/FunnelConversionWindowTimeUnit/type',
                                            keyword: 'type',
                                            params: { type: 'string' },
                                            message: 'must be string',
                                        },
                                    ]
                                    return false
                                }
                                if (
                                    !(
                                        data2 === 'second' ||
                                        data2 === 'minute' ||
                                        data2 === 'hour' ||
                                        data2 === 'day' ||
                                        data2 === 'week' ||
                                        data2 === 'month'
                                    )
                                ) {
                                    validate101.errors = [
                                        {
                                            instancePath: instancePath + '/conversion_window_unit',
                                            schemaPath: '#/definitions/FunnelConversionWindowTimeUnit/enum',
                                            keyword: 'enum',
                                            params: { allowedValues: schema72.enum },
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
                                if (data.fingerprint !== undefined) {
                                    const _errs9 = errors
                                    if (typeof data.fingerprint !== 'string') {
                                        validate101.errors = [
                                            {
                                                instancePath: instancePath + '/fingerprint',
                                                schemaPath: '#/properties/fingerprint/type',
                                                keyword: 'type',
                                                params: { type: 'string' },
                                                message: 'must be string',
                                            },
                                        ]
                                        return false
                                    }
                                    var valid0 = _errs9 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.funnel_order_type !== undefined) {
                                        let data4 = data.funnel_order_type
                                        const _errs11 = errors
                                        if (typeof data4 !== 'string') {
                                            validate101.errors = [
                                                {
                                                    instancePath: instancePath + '/funnel_order_type',
                                                    schemaPath: '#/definitions/StepOrderValue/type',
                                                    keyword: 'type',
                                                    params: { type: 'string' },
                                                    message: 'must be string',
                                                },
                                            ]
                                            return false
                                        }
                                        if (!(data4 === 'strict' || data4 === 'unordered' || data4 === 'ordered')) {
                                            validate101.errors = [
                                                {
                                                    instancePath: instancePath + '/funnel_order_type',
                                                    schemaPath: '#/definitions/StepOrderValue/enum',
                                                    keyword: 'enum',
                                                    params: { allowedValues: schema94.enum },
                                                    message: 'must be equal to one of the allowed values',
                                                },
                                            ]
                                            return false
                                        }
                                        var valid0 = _errs11 === errors
                                    } else {
                                        var valid0 = true
                                    }
                                    if (valid0) {
                                        if (data.goal !== undefined) {
                                            let data5 = data.goal
                                            const _errs14 = errors
                                            if (typeof data5 !== 'string') {
                                                validate101.errors = [
                                                    {
                                                        instancePath: instancePath + '/goal',
                                                        schemaPath: '#/definitions/ExperimentMetricGoal/type',
                                                        keyword: 'type',
                                                        params: { type: 'string' },
                                                        message: 'must be string',
                                                    },
                                                ]
                                                return false
                                            }
                                            if (!(data5 === 'increase' || data5 === 'decrease')) {
                                                validate101.errors = [
                                                    {
                                                        instancePath: instancePath + '/goal',
                                                        schemaPath: '#/definitions/ExperimentMetricGoal/enum',
                                                        keyword: 'enum',
                                                        params: { allowedValues: schema73.enum },
                                                        message: 'must be equal to one of the allowed values',
                                                    },
                                                ]
                                                return false
                                            }
                                            var valid0 = _errs14 === errors
                                        } else {
                                            var valid0 = true
                                        }
                                        if (valid0) {
                                            if (data.isSharedMetric !== undefined) {
                                                const _errs17 = errors
                                                if (typeof data.isSharedMetric !== 'boolean') {
                                                    validate101.errors = [
                                                        {
                                                            instancePath: instancePath + '/isSharedMetric',
                                                            schemaPath: '#/properties/isSharedMetric/type',
                                                            keyword: 'type',
                                                            params: { type: 'boolean' },
                                                            message: 'must be boolean',
                                                        },
                                                    ]
                                                    return false
                                                }
                                                var valid0 = _errs17 === errors
                                            } else {
                                                var valid0 = true
                                            }
                                            if (valid0) {
                                                if (data.kind !== undefined) {
                                                    let data7 = data.kind
                                                    const _errs19 = errors
                                                    if (typeof data7 !== 'string') {
                                                        validate101.errors = [
                                                            {
                                                                instancePath: instancePath + '/kind',
                                                                schemaPath: '#/properties/kind/type',
                                                                keyword: 'type',
                                                                params: { type: 'string' },
                                                                message: 'must be string',
                                                            },
                                                        ]
                                                        return false
                                                    }
                                                    if ('ExperimentMetric' !== data7) {
                                                        validate101.errors = [
                                                            {
                                                                instancePath: instancePath + '/kind',
                                                                schemaPath: '#/properties/kind/const',
                                                                keyword: 'const',
                                                                params: { allowedValue: 'ExperimentMetric' },
                                                                message: 'must be equal to constant',
                                                            },
                                                        ]
                                                        return false
                                                    }
                                                    var valid0 = _errs19 === errors
                                                } else {
                                                    var valid0 = true
                                                }
                                                if (valid0) {
                                                    if (data.metric_type !== undefined) {
                                                        let data8 = data.metric_type
                                                        const _errs21 = errors
                                                        if (typeof data8 !== 'string') {
                                                            validate101.errors = [
                                                                {
                                                                    instancePath: instancePath + '/metric_type',
                                                                    schemaPath: '#/properties/metric_type/type',
                                                                    keyword: 'type',
                                                                    params: { type: 'string' },
                                                                    message: 'must be string',
                                                                },
                                                            ]
                                                            return false
                                                        }
                                                        if ('funnel' !== data8) {
                                                            validate101.errors = [
                                                                {
                                                                    instancePath: instancePath + '/metric_type',
                                                                    schemaPath: '#/properties/metric_type/const',
                                                                    keyword: 'const',
                                                                    params: { allowedValue: 'funnel' },
                                                                    message: 'must be equal to constant',
                                                                },
                                                            ]
                                                            return false
                                                        }
                                                        var valid0 = _errs21 === errors
                                                    } else {
                                                        var valid0 = true
                                                    }
                                                    if (valid0) {
                                                        if (data.name !== undefined) {
                                                            const _errs23 = errors
                                                            if (typeof data.name !== 'string') {
                                                                validate101.errors = [
                                                                    {
                                                                        instancePath: instancePath + '/name',
                                                                        schemaPath: '#/properties/name/type',
                                                                        keyword: 'type',
                                                                        params: { type: 'string' },
                                                                        message: 'must be string',
                                                                    },
                                                                ]
                                                                return false
                                                            }
                                                            var valid0 = _errs23 === errors
                                                        } else {
                                                            var valid0 = true
                                                        }
                                                        if (valid0) {
                                                            if (data.response !== undefined) {
                                                                let data10 = data.response
                                                                const _errs25 = errors
                                                                if (
                                                                    !(
                                                                        data10 &&
                                                                        typeof data10 == 'object' &&
                                                                        !Array.isArray(data10)
                                                                    )
                                                                ) {
                                                                    validate101.errors = [
                                                                        {
                                                                            instancePath: instancePath + '/response',
                                                                            schemaPath: '#/properties/response/type',
                                                                            keyword: 'type',
                                                                            params: { type: 'object' },
                                                                            message: 'must be object',
                                                                        },
                                                                    ]
                                                                    return false
                                                                }
                                                                var valid0 = _errs25 === errors
                                                            } else {
                                                                var valid0 = true
                                                            }
                                                            if (valid0) {
                                                                if (data.series !== undefined) {
                                                                    let data11 = data.series
                                                                    const _errs27 = errors
                                                                    if (errors === _errs27) {
                                                                        if (Array.isArray(data11)) {
                                                                            var valid5 = true
                                                                            const len0 = data11.length
                                                                            for (let i0 = 0; i0 < len0; i0++) {
                                                                                const _errs29 = errors
                                                                                if (
                                                                                    !validate103(data11[i0], {
                                                                                        instancePath:
                                                                                            instancePath +
                                                                                            '/series/' +
                                                                                            i0,
                                                                                        parentData: data11,
                                                                                        parentDataProperty: i0,
                                                                                        rootData,
                                                                                    })
                                                                                ) {
                                                                                    vErrors =
                                                                                        vErrors === null
                                                                                            ? validate103.errors
                                                                                            : vErrors.concat(
                                                                                                  validate103.errors
                                                                                              )
                                                                                    errors = vErrors.length
                                                                                }
                                                                                var valid5 = _errs29 === errors
                                                                                if (!valid5) {
                                                                                    break
                                                                                }
                                                                            }
                                                                        } else {
                                                                            validate101.errors = [
                                                                                {
                                                                                    instancePath:
                                                                                        instancePath + '/series',
                                                                                    schemaPath:
                                                                                        '#/properties/series/type',
                                                                                    keyword: 'type',
                                                                                    params: { type: 'array' },
                                                                                    message: 'must be array',
                                                                                },
                                                                            ]
                                                                            return false
                                                                        }
                                                                    }
                                                                    var valid0 = _errs27 === errors
                                                                } else {
                                                                    var valid0 = true
                                                                }
                                                                if (valid0) {
                                                                    if (data.sharedMetricId !== undefined) {
                                                                        let data13 = data.sharedMetricId
                                                                        const _errs30 = errors
                                                                        if (
                                                                            !(
                                                                                typeof data13 == 'number' &&
                                                                                isFinite(data13)
                                                                            )
                                                                        ) {
                                                                            validate101.errors = [
                                                                                {
                                                                                    instancePath:
                                                                                        instancePath +
                                                                                        '/sharedMetricId',
                                                                                    schemaPath:
                                                                                        '#/properties/sharedMetricId/type',
                                                                                    keyword: 'type',
                                                                                    params: { type: 'number' },
                                                                                    message: 'must be number',
                                                                                },
                                                                            ]
                                                                            return false
                                                                        }
                                                                        var valid0 = _errs30 === errors
                                                                    } else {
                                                                        var valid0 = true
                                                                    }
                                                                    if (valid0) {
                                                                        if (data.uuid !== undefined) {
                                                                            const _errs32 = errors
                                                                            if (typeof data.uuid !== 'string') {
                                                                                validate101.errors = [
                                                                                    {
                                                                                        instancePath:
                                                                                            instancePath + '/uuid',
                                                                                        schemaPath:
                                                                                            '#/properties/uuid/type',
                                                                                        keyword: 'type',
                                                                                        params: { type: 'string' },
                                                                                        message: 'must be string',
                                                                                    },
                                                                                ]
                                                                                return false
                                                                            }
                                                                            var valid0 = _errs32 === errors
                                                                        } else {
                                                                            var valid0 = true
                                                                        }
                                                                        if (valid0) {
                                                                            if (data.version !== undefined) {
                                                                                let data15 = data.version
                                                                                const _errs34 = errors
                                                                                if (
                                                                                    !(
                                                                                        typeof data15 == 'number' &&
                                                                                        isFinite(data15)
                                                                                    )
                                                                                ) {
                                                                                    validate101.errors = [
                                                                                        {
                                                                                            instancePath:
                                                                                                instancePath +
                                                                                                '/version',
                                                                                            schemaPath:
                                                                                                '#/properties/version/type',
                                                                                            keyword: 'type',
                                                                                            params: { type: 'number' },
                                                                                            message: 'must be number',
                                                                                        },
                                                                                    ]
                                                                                    return false
                                                                                }
                                                                                var valid0 = _errs34 === errors
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
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } else {
            validate101.errors = [
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
    validate101.errors = vErrors
    return errors === 0
}
const schema97 = {
    additionalProperties: false,
    properties: {
        breakdownFilter: { $ref: '#/definitions/BreakdownFilter' },
        conversion_window: { $ref: '#/definitions/integer' },
        conversion_window_unit: { $ref: '#/definitions/FunnelConversionWindowTimeUnit' },
        denominator: { $ref: '#/definitions/ExperimentMetricSource' },
        fingerprint: { type: 'string' },
        goal: { $ref: '#/definitions/ExperimentMetricGoal' },
        isSharedMetric: { type: 'boolean' },
        kind: { const: 'ExperimentMetric', type: 'string' },
        metric_type: { const: 'ratio', type: 'string' },
        name: { type: 'string' },
        numerator: { $ref: '#/definitions/ExperimentMetricSource' },
        response: { type: 'object' },
        sharedMetricId: { type: 'number' },
        uuid: { type: 'string' },
        version: { description: 'version of the node, used for schema migrations', type: 'number' },
    },
    required: ['denominator', 'kind', 'metric_type', 'numerator'],
    type: 'object',
}
function validate108(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if (
                (data.denominator === undefined && (missing0 = 'denominator')) ||
                (data.kind === undefined && (missing0 = 'kind')) ||
                (data.metric_type === undefined && (missing0 = 'metric_type')) ||
                (data.numerator === undefined && (missing0 = 'numerator'))
            ) {
                validate108.errors = [
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
                    if (!func2.call(schema97.properties, key0)) {
                        validate108.errors = [
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
                    if (data.breakdownFilter !== undefined) {
                        const _errs2 = errors
                        if (
                            !validate74(data.breakdownFilter, {
                                instancePath: instancePath + '/breakdownFilter',
                                parentData: data,
                                parentDataProperty: 'breakdownFilter',
                                rootData,
                            })
                        ) {
                            vErrors = vErrors === null ? validate74.errors : vErrors.concat(validate74.errors)
                            errors = vErrors.length
                        }
                        var valid0 = _errs2 === errors
                    } else {
                        var valid0 = true
                    }
                    if (valid0) {
                        if (data.conversion_window !== undefined) {
                            let data1 = data.conversion_window
                            const _errs3 = errors
                            if (!(typeof data1 == 'number' && !(data1 % 1) && !isNaN(data1) && isFinite(data1))) {
                                validate108.errors = [
                                    {
                                        instancePath: instancePath + '/conversion_window',
                                        schemaPath: '#/definitions/integer/type',
                                        keyword: 'type',
                                        params: { type: 'integer' },
                                        message: 'must be integer',
                                    },
                                ]
                                return false
                            }
                            var valid0 = _errs3 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.conversion_window_unit !== undefined) {
                                let data2 = data.conversion_window_unit
                                const _errs6 = errors
                                if (typeof data2 !== 'string') {
                                    validate108.errors = [
                                        {
                                            instancePath: instancePath + '/conversion_window_unit',
                                            schemaPath: '#/definitions/FunnelConversionWindowTimeUnit/type',
                                            keyword: 'type',
                                            params: { type: 'string' },
                                            message: 'must be string',
                                        },
                                    ]
                                    return false
                                }
                                if (
                                    !(
                                        data2 === 'second' ||
                                        data2 === 'minute' ||
                                        data2 === 'hour' ||
                                        data2 === 'day' ||
                                        data2 === 'week' ||
                                        data2 === 'month'
                                    )
                                ) {
                                    validate108.errors = [
                                        {
                                            instancePath: instancePath + '/conversion_window_unit',
                                            schemaPath: '#/definitions/FunnelConversionWindowTimeUnit/enum',
                                            keyword: 'enum',
                                            params: { allowedValues: schema72.enum },
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
                                if (data.denominator !== undefined) {
                                    const _errs9 = errors
                                    if (
                                        !validate78(data.denominator, {
                                            instancePath: instancePath + '/denominator',
                                            parentData: data,
                                            parentDataProperty: 'denominator',
                                            rootData,
                                        })
                                    ) {
                                        vErrors =
                                            vErrors === null ? validate78.errors : vErrors.concat(validate78.errors)
                                        errors = vErrors.length
                                    }
                                    var valid0 = _errs9 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.fingerprint !== undefined) {
                                        const _errs10 = errors
                                        if (typeof data.fingerprint !== 'string') {
                                            validate108.errors = [
                                                {
                                                    instancePath: instancePath + '/fingerprint',
                                                    schemaPath: '#/properties/fingerprint/type',
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
                                        if (data.goal !== undefined) {
                                            let data5 = data.goal
                                            const _errs12 = errors
                                            if (typeof data5 !== 'string') {
                                                validate108.errors = [
                                                    {
                                                        instancePath: instancePath + '/goal',
                                                        schemaPath: '#/definitions/ExperimentMetricGoal/type',
                                                        keyword: 'type',
                                                        params: { type: 'string' },
                                                        message: 'must be string',
                                                    },
                                                ]
                                                return false
                                            }
                                            if (!(data5 === 'increase' || data5 === 'decrease')) {
                                                validate108.errors = [
                                                    {
                                                        instancePath: instancePath + '/goal',
                                                        schemaPath: '#/definitions/ExperimentMetricGoal/enum',
                                                        keyword: 'enum',
                                                        params: { allowedValues: schema73.enum },
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
                                            if (data.isSharedMetric !== undefined) {
                                                const _errs15 = errors
                                                if (typeof data.isSharedMetric !== 'boolean') {
                                                    validate108.errors = [
                                                        {
                                                            instancePath: instancePath + '/isSharedMetric',
                                                            schemaPath: '#/properties/isSharedMetric/type',
                                                            keyword: 'type',
                                                            params: { type: 'boolean' },
                                                            message: 'must be boolean',
                                                        },
                                                    ]
                                                    return false
                                                }
                                                var valid0 = _errs15 === errors
                                            } else {
                                                var valid0 = true
                                            }
                                            if (valid0) {
                                                if (data.kind !== undefined) {
                                                    let data7 = data.kind
                                                    const _errs17 = errors
                                                    if (typeof data7 !== 'string') {
                                                        validate108.errors = [
                                                            {
                                                                instancePath: instancePath + '/kind',
                                                                schemaPath: '#/properties/kind/type',
                                                                keyword: 'type',
                                                                params: { type: 'string' },
                                                                message: 'must be string',
                                                            },
                                                        ]
                                                        return false
                                                    }
                                                    if ('ExperimentMetric' !== data7) {
                                                        validate108.errors = [
                                                            {
                                                                instancePath: instancePath + '/kind',
                                                                schemaPath: '#/properties/kind/const',
                                                                keyword: 'const',
                                                                params: { allowedValue: 'ExperimentMetric' },
                                                                message: 'must be equal to constant',
                                                            },
                                                        ]
                                                        return false
                                                    }
                                                    var valid0 = _errs17 === errors
                                                } else {
                                                    var valid0 = true
                                                }
                                                if (valid0) {
                                                    if (data.metric_type !== undefined) {
                                                        let data8 = data.metric_type
                                                        const _errs19 = errors
                                                        if (typeof data8 !== 'string') {
                                                            validate108.errors = [
                                                                {
                                                                    instancePath: instancePath + '/metric_type',
                                                                    schemaPath: '#/properties/metric_type/type',
                                                                    keyword: 'type',
                                                                    params: { type: 'string' },
                                                                    message: 'must be string',
                                                                },
                                                            ]
                                                            return false
                                                        }
                                                        if ('ratio' !== data8) {
                                                            validate108.errors = [
                                                                {
                                                                    instancePath: instancePath + '/metric_type',
                                                                    schemaPath: '#/properties/metric_type/const',
                                                                    keyword: 'const',
                                                                    params: { allowedValue: 'ratio' },
                                                                    message: 'must be equal to constant',
                                                                },
                                                            ]
                                                            return false
                                                        }
                                                        var valid0 = _errs19 === errors
                                                    } else {
                                                        var valid0 = true
                                                    }
                                                    if (valid0) {
                                                        if (data.name !== undefined) {
                                                            const _errs21 = errors
                                                            if (typeof data.name !== 'string') {
                                                                validate108.errors = [
                                                                    {
                                                                        instancePath: instancePath + '/name',
                                                                        schemaPath: '#/properties/name/type',
                                                                        keyword: 'type',
                                                                        params: { type: 'string' },
                                                                        message: 'must be string',
                                                                    },
                                                                ]
                                                                return false
                                                            }
                                                            var valid0 = _errs21 === errors
                                                        } else {
                                                            var valid0 = true
                                                        }
                                                        if (valid0) {
                                                            if (data.numerator !== undefined) {
                                                                const _errs23 = errors
                                                                if (
                                                                    !validate78(data.numerator, {
                                                                        instancePath: instancePath + '/numerator',
                                                                        parentData: data,
                                                                        parentDataProperty: 'numerator',
                                                                        rootData,
                                                                    })
                                                                ) {
                                                                    vErrors =
                                                                        vErrors === null
                                                                            ? validate78.errors
                                                                            : vErrors.concat(validate78.errors)
                                                                    errors = vErrors.length
                                                                }
                                                                var valid0 = _errs23 === errors
                                                            } else {
                                                                var valid0 = true
                                                            }
                                                            if (valid0) {
                                                                if (data.response !== undefined) {
                                                                    let data11 = data.response
                                                                    const _errs24 = errors
                                                                    if (
                                                                        !(
                                                                            data11 &&
                                                                            typeof data11 == 'object' &&
                                                                            !Array.isArray(data11)
                                                                        )
                                                                    ) {
                                                                        validate108.errors = [
                                                                            {
                                                                                instancePath:
                                                                                    instancePath + '/response',
                                                                                schemaPath:
                                                                                    '#/properties/response/type',
                                                                                keyword: 'type',
                                                                                params: { type: 'object' },
                                                                                message: 'must be object',
                                                                            },
                                                                        ]
                                                                        return false
                                                                    }
                                                                    var valid0 = _errs24 === errors
                                                                } else {
                                                                    var valid0 = true
                                                                }
                                                                if (valid0) {
                                                                    if (data.sharedMetricId !== undefined) {
                                                                        let data12 = data.sharedMetricId
                                                                        const _errs26 = errors
                                                                        if (
                                                                            !(
                                                                                typeof data12 == 'number' &&
                                                                                isFinite(data12)
                                                                            )
                                                                        ) {
                                                                            validate108.errors = [
                                                                                {
                                                                                    instancePath:
                                                                                        instancePath +
                                                                                        '/sharedMetricId',
                                                                                    schemaPath:
                                                                                        '#/properties/sharedMetricId/type',
                                                                                    keyword: 'type',
                                                                                    params: { type: 'number' },
                                                                                    message: 'must be number',
                                                                                },
                                                                            ]
                                                                            return false
                                                                        }
                                                                        var valid0 = _errs26 === errors
                                                                    } else {
                                                                        var valid0 = true
                                                                    }
                                                                    if (valid0) {
                                                                        if (data.uuid !== undefined) {
                                                                            const _errs28 = errors
                                                                            if (typeof data.uuid !== 'string') {
                                                                                validate108.errors = [
                                                                                    {
                                                                                        instancePath:
                                                                                            instancePath + '/uuid',
                                                                                        schemaPath:
                                                                                            '#/properties/uuid/type',
                                                                                        keyword: 'type',
                                                                                        params: { type: 'string' },
                                                                                        message: 'must be string',
                                                                                    },
                                                                                ]
                                                                                return false
                                                                            }
                                                                            var valid0 = _errs28 === errors
                                                                        } else {
                                                                            var valid0 = true
                                                                        }
                                                                        if (valid0) {
                                                                            if (data.version !== undefined) {
                                                                                let data14 = data.version
                                                                                const _errs30 = errors
                                                                                if (
                                                                                    !(
                                                                                        typeof data14 == 'number' &&
                                                                                        isFinite(data14)
                                                                                    )
                                                                                ) {
                                                                                    validate108.errors = [
                                                                                        {
                                                                                            instancePath:
                                                                                                instancePath +
                                                                                                '/version',
                                                                                            schemaPath:
                                                                                                '#/properties/version/type',
                                                                                            keyword: 'type',
                                                                                            params: { type: 'number' },
                                                                                            message: 'must be number',
                                                                                        },
                                                                                    ]
                                                                                    return false
                                                                                }
                                                                                var valid0 = _errs30 === errors
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
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } else {
            validate108.errors = [
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
    validate108.errors = vErrors
    return errors === 0
}
const schema101 = {
    additionalProperties: false,
    properties: {
        breakdownFilter: { $ref: '#/definitions/BreakdownFilter' },
        completion_event: { $ref: '#/definitions/ExperimentMetricSource' },
        conversion_window: { $ref: '#/definitions/integer' },
        conversion_window_unit: { $ref: '#/definitions/FunnelConversionWindowTimeUnit' },
        fingerprint: { type: 'string' },
        goal: { $ref: '#/definitions/ExperimentMetricGoal' },
        isSharedMetric: { type: 'boolean' },
        kind: { const: 'ExperimentMetric', type: 'string' },
        metric_type: { const: 'retention', type: 'string' },
        name: { type: 'string' },
        response: { type: 'object' },
        retention_window_end: { $ref: '#/definitions/integer' },
        retention_window_start: { $ref: '#/definitions/integer' },
        retention_window_unit: { $ref: '#/definitions/FunnelConversionWindowTimeUnit' },
        sharedMetricId: { type: 'number' },
        start_event: { $ref: '#/definitions/ExperimentMetricSource' },
        start_handling: { enum: ['first_seen', 'last_seen'], type: 'string' },
        uuid: { type: 'string' },
        version: { description: 'version of the node, used for schema migrations', type: 'number' },
    },
    required: [
        'completion_event',
        'kind',
        'metric_type',
        'retention_window_end',
        'retention_window_start',
        'retention_window_unit',
        'start_event',
        'start_handling',
    ],
    type: 'object',
}
function validate113(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    if (errors === 0) {
        if (data && typeof data == 'object' && !Array.isArray(data)) {
            let missing0
            if (
                (data.completion_event === undefined && (missing0 = 'completion_event')) ||
                (data.kind === undefined && (missing0 = 'kind')) ||
                (data.metric_type === undefined && (missing0 = 'metric_type')) ||
                (data.retention_window_end === undefined && (missing0 = 'retention_window_end')) ||
                (data.retention_window_start === undefined && (missing0 = 'retention_window_start')) ||
                (data.retention_window_unit === undefined && (missing0 = 'retention_window_unit')) ||
                (data.start_event === undefined && (missing0 = 'start_event')) ||
                (data.start_handling === undefined && (missing0 = 'start_handling'))
            ) {
                validate113.errors = [
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
                    if (!func2.call(schema101.properties, key0)) {
                        validate113.errors = [
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
                    if (data.breakdownFilter !== undefined) {
                        const _errs2 = errors
                        if (
                            !validate74(data.breakdownFilter, {
                                instancePath: instancePath + '/breakdownFilter',
                                parentData: data,
                                parentDataProperty: 'breakdownFilter',
                                rootData,
                            })
                        ) {
                            vErrors = vErrors === null ? validate74.errors : vErrors.concat(validate74.errors)
                            errors = vErrors.length
                        }
                        var valid0 = _errs2 === errors
                    } else {
                        var valid0 = true
                    }
                    if (valid0) {
                        if (data.completion_event !== undefined) {
                            const _errs3 = errors
                            if (
                                !validate78(data.completion_event, {
                                    instancePath: instancePath + '/completion_event',
                                    parentData: data,
                                    parentDataProperty: 'completion_event',
                                    rootData,
                                })
                            ) {
                                vErrors = vErrors === null ? validate78.errors : vErrors.concat(validate78.errors)
                                errors = vErrors.length
                            }
                            var valid0 = _errs3 === errors
                        } else {
                            var valid0 = true
                        }
                        if (valid0) {
                            if (data.conversion_window !== undefined) {
                                let data2 = data.conversion_window
                                const _errs4 = errors
                                if (!(typeof data2 == 'number' && !(data2 % 1) && !isNaN(data2) && isFinite(data2))) {
                                    validate113.errors = [
                                        {
                                            instancePath: instancePath + '/conversion_window',
                                            schemaPath: '#/definitions/integer/type',
                                            keyword: 'type',
                                            params: { type: 'integer' },
                                            message: 'must be integer',
                                        },
                                    ]
                                    return false
                                }
                                var valid0 = _errs4 === errors
                            } else {
                                var valid0 = true
                            }
                            if (valid0) {
                                if (data.conversion_window_unit !== undefined) {
                                    let data3 = data.conversion_window_unit
                                    const _errs7 = errors
                                    if (typeof data3 !== 'string') {
                                        validate113.errors = [
                                            {
                                                instancePath: instancePath + '/conversion_window_unit',
                                                schemaPath: '#/definitions/FunnelConversionWindowTimeUnit/type',
                                                keyword: 'type',
                                                params: { type: 'string' },
                                                message: 'must be string',
                                            },
                                        ]
                                        return false
                                    }
                                    if (
                                        !(
                                            data3 === 'second' ||
                                            data3 === 'minute' ||
                                            data3 === 'hour' ||
                                            data3 === 'day' ||
                                            data3 === 'week' ||
                                            data3 === 'month'
                                        )
                                    ) {
                                        validate113.errors = [
                                            {
                                                instancePath: instancePath + '/conversion_window_unit',
                                                schemaPath: '#/definitions/FunnelConversionWindowTimeUnit/enum',
                                                keyword: 'enum',
                                                params: { allowedValues: schema72.enum },
                                                message: 'must be equal to one of the allowed values',
                                            },
                                        ]
                                        return false
                                    }
                                    var valid0 = _errs7 === errors
                                } else {
                                    var valid0 = true
                                }
                                if (valid0) {
                                    if (data.fingerprint !== undefined) {
                                        const _errs10 = errors
                                        if (typeof data.fingerprint !== 'string') {
                                            validate113.errors = [
                                                {
                                                    instancePath: instancePath + '/fingerprint',
                                                    schemaPath: '#/properties/fingerprint/type',
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
                                        if (data.goal !== undefined) {
                                            let data5 = data.goal
                                            const _errs12 = errors
                                            if (typeof data5 !== 'string') {
                                                validate113.errors = [
                                                    {
                                                        instancePath: instancePath + '/goal',
                                                        schemaPath: '#/definitions/ExperimentMetricGoal/type',
                                                        keyword: 'type',
                                                        params: { type: 'string' },
                                                        message: 'must be string',
                                                    },
                                                ]
                                                return false
                                            }
                                            if (!(data5 === 'increase' || data5 === 'decrease')) {
                                                validate113.errors = [
                                                    {
                                                        instancePath: instancePath + '/goal',
                                                        schemaPath: '#/definitions/ExperimentMetricGoal/enum',
                                                        keyword: 'enum',
                                                        params: { allowedValues: schema73.enum },
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
                                            if (data.isSharedMetric !== undefined) {
                                                const _errs15 = errors
                                                if (typeof data.isSharedMetric !== 'boolean') {
                                                    validate113.errors = [
                                                        {
                                                            instancePath: instancePath + '/isSharedMetric',
                                                            schemaPath: '#/properties/isSharedMetric/type',
                                                            keyword: 'type',
                                                            params: { type: 'boolean' },
                                                            message: 'must be boolean',
                                                        },
                                                    ]
                                                    return false
                                                }
                                                var valid0 = _errs15 === errors
                                            } else {
                                                var valid0 = true
                                            }
                                            if (valid0) {
                                                if (data.kind !== undefined) {
                                                    let data7 = data.kind
                                                    const _errs17 = errors
                                                    if (typeof data7 !== 'string') {
                                                        validate113.errors = [
                                                            {
                                                                instancePath: instancePath + '/kind',
                                                                schemaPath: '#/properties/kind/type',
                                                                keyword: 'type',
                                                                params: { type: 'string' },
                                                                message: 'must be string',
                                                            },
                                                        ]
                                                        return false
                                                    }
                                                    if ('ExperimentMetric' !== data7) {
                                                        validate113.errors = [
                                                            {
                                                                instancePath: instancePath + '/kind',
                                                                schemaPath: '#/properties/kind/const',
                                                                keyword: 'const',
                                                                params: { allowedValue: 'ExperimentMetric' },
                                                                message: 'must be equal to constant',
                                                            },
                                                        ]
                                                        return false
                                                    }
                                                    var valid0 = _errs17 === errors
                                                } else {
                                                    var valid0 = true
                                                }
                                                if (valid0) {
                                                    if (data.metric_type !== undefined) {
                                                        let data8 = data.metric_type
                                                        const _errs19 = errors
                                                        if (typeof data8 !== 'string') {
                                                            validate113.errors = [
                                                                {
                                                                    instancePath: instancePath + '/metric_type',
                                                                    schemaPath: '#/properties/metric_type/type',
                                                                    keyword: 'type',
                                                                    params: { type: 'string' },
                                                                    message: 'must be string',
                                                                },
                                                            ]
                                                            return false
                                                        }
                                                        if ('retention' !== data8) {
                                                            validate113.errors = [
                                                                {
                                                                    instancePath: instancePath + '/metric_type',
                                                                    schemaPath: '#/properties/metric_type/const',
                                                                    keyword: 'const',
                                                                    params: { allowedValue: 'retention' },
                                                                    message: 'must be equal to constant',
                                                                },
                                                            ]
                                                            return false
                                                        }
                                                        var valid0 = _errs19 === errors
                                                    } else {
                                                        var valid0 = true
                                                    }
                                                    if (valid0) {
                                                        if (data.name !== undefined) {
                                                            const _errs21 = errors
                                                            if (typeof data.name !== 'string') {
                                                                validate113.errors = [
                                                                    {
                                                                        instancePath: instancePath + '/name',
                                                                        schemaPath: '#/properties/name/type',
                                                                        keyword: 'type',
                                                                        params: { type: 'string' },
                                                                        message: 'must be string',
                                                                    },
                                                                ]
                                                                return false
                                                            }
                                                            var valid0 = _errs21 === errors
                                                        } else {
                                                            var valid0 = true
                                                        }
                                                        if (valid0) {
                                                            if (data.response !== undefined) {
                                                                let data10 = data.response
                                                                const _errs23 = errors
                                                                if (
                                                                    !(
                                                                        data10 &&
                                                                        typeof data10 == 'object' &&
                                                                        !Array.isArray(data10)
                                                                    )
                                                                ) {
                                                                    validate113.errors = [
                                                                        {
                                                                            instancePath: instancePath + '/response',
                                                                            schemaPath: '#/properties/response/type',
                                                                            keyword: 'type',
                                                                            params: { type: 'object' },
                                                                            message: 'must be object',
                                                                        },
                                                                    ]
                                                                    return false
                                                                }
                                                                var valid0 = _errs23 === errors
                                                            } else {
                                                                var valid0 = true
                                                            }
                                                            if (valid0) {
                                                                if (data.retention_window_end !== undefined) {
                                                                    let data11 = data.retention_window_end
                                                                    const _errs25 = errors
                                                                    if (
                                                                        !(
                                                                            typeof data11 == 'number' &&
                                                                            !(data11 % 1) &&
                                                                            !isNaN(data11) &&
                                                                            isFinite(data11)
                                                                        )
                                                                    ) {
                                                                        validate113.errors = [
                                                                            {
                                                                                instancePath:
                                                                                    instancePath +
                                                                                    '/retention_window_end',
                                                                                schemaPath:
                                                                                    '#/definitions/integer/type',
                                                                                keyword: 'type',
                                                                                params: { type: 'integer' },
                                                                                message: 'must be integer',
                                                                            },
                                                                        ]
                                                                        return false
                                                                    }
                                                                    var valid0 = _errs25 === errors
                                                                } else {
                                                                    var valid0 = true
                                                                }
                                                                if (valid0) {
                                                                    if (data.retention_window_start !== undefined) {
                                                                        let data12 = data.retention_window_start
                                                                        const _errs28 = errors
                                                                        if (
                                                                            !(
                                                                                typeof data12 == 'number' &&
                                                                                !(data12 % 1) &&
                                                                                !isNaN(data12) &&
                                                                                isFinite(data12)
                                                                            )
                                                                        ) {
                                                                            validate113.errors = [
                                                                                {
                                                                                    instancePath:
                                                                                        instancePath +
                                                                                        '/retention_window_start',
                                                                                    schemaPath:
                                                                                        '#/definitions/integer/type',
                                                                                    keyword: 'type',
                                                                                    params: { type: 'integer' },
                                                                                    message: 'must be integer',
                                                                                },
                                                                            ]
                                                                            return false
                                                                        }
                                                                        var valid0 = _errs28 === errors
                                                                    } else {
                                                                        var valid0 = true
                                                                    }
                                                                    if (valid0) {
                                                                        if (data.retention_window_unit !== undefined) {
                                                                            let data13 = data.retention_window_unit
                                                                            const _errs31 = errors
                                                                            if (typeof data13 !== 'string') {
                                                                                validate113.errors = [
                                                                                    {
                                                                                        instancePath:
                                                                                            instancePath +
                                                                                            '/retention_window_unit',
                                                                                        schemaPath:
                                                                                            '#/definitions/FunnelConversionWindowTimeUnit/type',
                                                                                        keyword: 'type',
                                                                                        params: { type: 'string' },
                                                                                        message: 'must be string',
                                                                                    },
                                                                                ]
                                                                                return false
                                                                            }
                                                                            if (
                                                                                !(
                                                                                    data13 === 'second' ||
                                                                                    data13 === 'minute' ||
                                                                                    data13 === 'hour' ||
                                                                                    data13 === 'day' ||
                                                                                    data13 === 'week' ||
                                                                                    data13 === 'month'
                                                                                )
                                                                            ) {
                                                                                validate113.errors = [
                                                                                    {
                                                                                        instancePath:
                                                                                            instancePath +
                                                                                            '/retention_window_unit',
                                                                                        schemaPath:
                                                                                            '#/definitions/FunnelConversionWindowTimeUnit/enum',
                                                                                        keyword: 'enum',
                                                                                        params: {
                                                                                            allowedValues:
                                                                                                schema72.enum,
                                                                                        },
                                                                                        message:
                                                                                            'must be equal to one of the allowed values',
                                                                                    },
                                                                                ]
                                                                                return false
                                                                            }
                                                                            var valid0 = _errs31 === errors
                                                                        } else {
                                                                            var valid0 = true
                                                                        }
                                                                        if (valid0) {
                                                                            if (data.sharedMetricId !== undefined) {
                                                                                let data14 = data.sharedMetricId
                                                                                const _errs34 = errors
                                                                                if (
                                                                                    !(
                                                                                        typeof data14 == 'number' &&
                                                                                        isFinite(data14)
                                                                                    )
                                                                                ) {
                                                                                    validate113.errors = [
                                                                                        {
                                                                                            instancePath:
                                                                                                instancePath +
                                                                                                '/sharedMetricId',
                                                                                            schemaPath:
                                                                                                '#/properties/sharedMetricId/type',
                                                                                            keyword: 'type',
                                                                                            params: { type: 'number' },
                                                                                            message: 'must be number',
                                                                                        },
                                                                                    ]
                                                                                    return false
                                                                                }
                                                                                var valid0 = _errs34 === errors
                                                                            } else {
                                                                                var valid0 = true
                                                                            }
                                                                            if (valid0) {
                                                                                if (data.start_event !== undefined) {
                                                                                    const _errs36 = errors
                                                                                    if (
                                                                                        !validate78(data.start_event, {
                                                                                            instancePath:
                                                                                                instancePath +
                                                                                                '/start_event',
                                                                                            parentData: data,
                                                                                            parentDataProperty:
                                                                                                'start_event',
                                                                                            rootData,
                                                                                        })
                                                                                    ) {
                                                                                        vErrors =
                                                                                            vErrors === null
                                                                                                ? validate78.errors
                                                                                                : vErrors.concat(
                                                                                                      validate78.errors
                                                                                                  )
                                                                                        errors = vErrors.length
                                                                                    }
                                                                                    var valid0 = _errs36 === errors
                                                                                } else {
                                                                                    var valid0 = true
                                                                                }
                                                                                if (valid0) {
                                                                                    if (
                                                                                        data.start_handling !==
                                                                                        undefined
                                                                                    ) {
                                                                                        let data16 = data.start_handling
                                                                                        const _errs37 = errors
                                                                                        if (
                                                                                            typeof data16 !== 'string'
                                                                                        ) {
                                                                                            validate113.errors = [
                                                                                                {
                                                                                                    instancePath:
                                                                                                        instancePath +
                                                                                                        '/start_handling',
                                                                                                    schemaPath:
                                                                                                        '#/properties/start_handling/type',
                                                                                                    keyword: 'type',
                                                                                                    params: {
                                                                                                        type: 'string',
                                                                                                    },
                                                                                                    message:
                                                                                                        'must be string',
                                                                                                },
                                                                                            ]
                                                                                            return false
                                                                                        }
                                                                                        if (
                                                                                            !(
                                                                                                data16 ===
                                                                                                    'first_seen' ||
                                                                                                data16 === 'last_seen'
                                                                                            )
                                                                                        ) {
                                                                                            validate113.errors = [
                                                                                                {
                                                                                                    instancePath:
                                                                                                        instancePath +
                                                                                                        '/start_handling',
                                                                                                    schemaPath:
                                                                                                        '#/properties/start_handling/enum',
                                                                                                    keyword: 'enum',
                                                                                                    params: {
                                                                                                        allowedValues:
                                                                                                            schema101
                                                                                                                .properties
                                                                                                                .start_handling
                                                                                                                .enum,
                                                                                                    },
                                                                                                    message:
                                                                                                        'must be equal to one of the allowed values',
                                                                                                },
                                                                                            ]
                                                                                            return false
                                                                                        }
                                                                                        var valid0 = _errs37 === errors
                                                                                    } else {
                                                                                        var valid0 = true
                                                                                    }
                                                                                    if (valid0) {
                                                                                        if (data.uuid !== undefined) {
                                                                                            const _errs39 = errors
                                                                                            if (
                                                                                                typeof data.uuid !==
                                                                                                'string'
                                                                                            ) {
                                                                                                validate113.errors = [
                                                                                                    {
                                                                                                        instancePath:
                                                                                                            instancePath +
                                                                                                            '/uuid',
                                                                                                        schemaPath:
                                                                                                            '#/properties/uuid/type',
                                                                                                        keyword: 'type',
                                                                                                        params: {
                                                                                                            type: 'string',
                                                                                                        },
                                                                                                        message:
                                                                                                            'must be string',
                                                                                                    },
                                                                                                ]
                                                                                                return false
                                                                                            }
                                                                                            var valid0 =
                                                                                                _errs39 === errors
                                                                                        } else {
                                                                                            var valid0 = true
                                                                                        }
                                                                                        if (valid0) {
                                                                                            if (
                                                                                                data.version !==
                                                                                                undefined
                                                                                            ) {
                                                                                                let data18 =
                                                                                                    data.version
                                                                                                const _errs41 = errors
                                                                                                if (
                                                                                                    !(
                                                                                                        typeof data18 ==
                                                                                                            'number' &&
                                                                                                        isFinite(data18)
                                                                                                    )
                                                                                                ) {
                                                                                                    validate113.errors =
                                                                                                        [
                                                                                                            {
                                                                                                                instancePath:
                                                                                                                    instancePath +
                                                                                                                    '/version',
                                                                                                                schemaPath:
                                                                                                                    '#/properties/version/type',
                                                                                                                keyword:
                                                                                                                    'type',
                                                                                                                params: {
                                                                                                                    type: 'number',
                                                                                                                },
                                                                                                                message:
                                                                                                                    'must be number',
                                                                                                            },
                                                                                                        ]
                                                                                                    return false
                                                                                                }
                                                                                                var valid0 =
                                                                                                    _errs41 === errors
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
        } else {
            validate113.errors = [
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
    validate113.errors = vErrors
    return errors === 0
}
function validate72(data, { instancePath = '', parentData, parentDataProperty, rootData = data } = {}) {
    let vErrors = null
    let errors = 0
    const _errs0 = errors
    let valid0 = false
    const _errs1 = errors
    if (!validate73(data, { instancePath, parentData, parentDataProperty, rootData })) {
        vErrors = vErrors === null ? validate73.errors : vErrors.concat(validate73.errors)
        errors = vErrors.length
    }
    var _valid0 = _errs1 === errors
    valid0 = valid0 || _valid0
    if (!valid0) {
        const _errs2 = errors
        if (!validate101(data, { instancePath, parentData, parentDataProperty, rootData })) {
            vErrors = vErrors === null ? validate101.errors : vErrors.concat(validate101.errors)
            errors = vErrors.length
        }
        var _valid0 = _errs2 === errors
        valid0 = valid0 || _valid0
        if (!valid0) {
            const _errs3 = errors
            if (!validate108(data, { instancePath, parentData, parentDataProperty, rootData })) {
                vErrors = vErrors === null ? validate108.errors : vErrors.concat(validate108.errors)
                errors = vErrors.length
            }
            var _valid0 = _errs3 === errors
            valid0 = valid0 || _valid0
            if (!valid0) {
                const _errs4 = errors
                if (!validate113(data, { instancePath, parentData, parentDataProperty, rootData })) {
                    vErrors = vErrors === null ? validate113.errors : vErrors.concat(validate113.errors)
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
        validate72.errors = vErrors
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
    validate72.errors = vErrors
    return errors === 0
}
