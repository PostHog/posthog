import React, { useState, useEffect, CSSProperties } from 'react'
import { Select } from 'antd'
import api from '../../api'
import { isOperatorFlag } from 'lib/utils'
import { SelectGradientOverflow } from 'lib/components/SelectGradientOverflow'

interface Option {
    id?: any
    values: any
    name?: any
    status: boolean | 'loading'
}

interface Options {
    [propertyKey: string]: Option
}

type OptionsCache = Record<any, true | 'loading'>

export interface PropertyValueProps {
    propertyKey: string
    type: string
    endpoint: string
    placeholder: string
    style?: CSSProperties
    bordered?: boolean
    onSet: (value: any) => void
    value: any
    operator: string
    outerOptions?: Option[]
}

export function PropertyValue({
    propertyKey,
    type,
    endpoint,
    placeholder,
    style,
    bordered,
    onSet,
    value,
    operator,
    outerOptions,
}: PropertyValueProps): JSX.Element {
    const [input, setInput] = useState('')
    const [optionsCache, setOptionsCache] = useState<OptionsCache>({})
    const [options, setOptions] = useState<Options>({})

    function loadPropertyValues(value: any): void {
        if (type === 'cohort') return
        const key = propertyKey.split('__')[0]
        setOptions({ [propertyKey]: { ...options[propertyKey], status: 'loading' }, ...options })
        setOptionsCache({ ...optionsCache, [value]: 'loading' })
        if (outerOptions) {
            setOptions({
                [propertyKey]: { values: [...new Set([...outerOptions.map((option) => option)])], status: true },
                ...options,
            })
            setOptionsCache({ ...optionsCache, [value]: true })
        } else {
            api.get(
                endpoint || 'api/projects/@current/' + type + 's/values/?key=' + key + (value ? '&value=' + value : '')
            ).then((propValues) => {
                setOptions({
                    [propertyKey]: { values: [...new Set([...propValues.map((option) => option)])], status: true },
                    ...options,
                })
                setOptionsCache({ ...optionsCache, [value]: true })
            })
        }
    }

    useEffect(() => {
        loadPropertyValues('')
    }, [propertyKey])

    const displayOptions: Option[] = (options[propertyKey]?.values ?? []).filter(
        (option) => !input || (option && option.name?.toLowerCase().indexOf(input.toLowerCase()) > -1)
    )

    return (
        <SelectGradientOverflow
            showSearch
            autoFocus={!value}
            style={{ width: '100%', ...style }}
            onChange={(_, payload) => onSet(payload?.value ?? null)}
            value={value || placeholder}
            loading={optionsCache[input] === 'loading'}
            onSearch={(input) => {
                setInput(input)
                if (!optionsCache[input] && !isOperatorFlag(operator)) loadPropertyValues(input)
            }}
            data-attr="prop-val"
            dropdownMatchSelectWidth={350}
            bordered={bordered}
            placeholder={placeholder}
            allowClear={value}
        >
            {input && (
                <Select.Option key={input} value={input}>
                    Specify: {input}
                </Select.Option>
            )}
            {displayOptions.map(({ name, id }, index) => (
                <Select.Option key={id || name} value={id || name} data-attr={'prop-val-' + index}>
                    {name === true ? 'true' : name === false ? 'false' : name}
                </Select.Option>
            ))}
        </SelectGradientOverflow>
    )
}
