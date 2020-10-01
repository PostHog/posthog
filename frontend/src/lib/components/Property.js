import React from 'react'

export function Property({ value }) {
    return (
        <>
            {typeof value === 'object' ? JSON.stringify(value) : value && value.toString().replace(/(^\w+:|^)\/\//, '')}
        </>
    )
}
