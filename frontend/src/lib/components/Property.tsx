import React from 'react'

export function Property({ value }: { value: any }): JSX.Element {
    return (
        <span title={value}>
            {typeof value === 'object' ? JSON.stringify(value) : value && value.toString().replace(/(^\w+:|^)\/\//, '')}
        </span>
    )
}
