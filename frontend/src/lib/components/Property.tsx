import React from 'react'

export function Property({ value }: { value: any }): JSX.Element {
    return (
        <>
            {typeof value === 'object' ? JSON.stringify(value) : value && value.toString().replace(/(^\w+:|^)\/\//, '')}
        </>
    )
}
