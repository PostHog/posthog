import React from 'react'
import { FontSizeOutlined, LinkOutlined, FormOutlined, BranchesOutlined } from '@ant-design/icons'

function SelectorString({ value }: { value: string }): JSX.Element {
    const [last, ...rest] = value.split(' ').reverse()
    return (
        <>
            {rest.reverse().join(' ')} <strong>{last}</strong>
        </>
    )
}

export function ActionAttribute({ attribute, value }: { attribute: string; value?: string }): JSX.Element {
    const icon =
        attribute === 'text' ? (
            <FontSizeOutlined />
        ) : attribute === 'href' ? (
            <LinkOutlined />
        ) : attribute === 'selector' ? (
            <BranchesOutlined />
        ) : (
            <FormOutlined />
        )

    const text =
        attribute === 'href' ? (
            <a href={value} target="_blank" rel="noopener noreferrer">
                {value}
            </a>
        ) : attribute === 'selector' ? (
            <span style={{ fontFamily: 'monospace' }}>
                <SelectorString value={value || ''} />
            </span>
        ) : (
            value
        )

    return (
        <div key={attribute} style={{ marginBottom: 10, paddingLeft: 24, position: 'relative' }}>
            <div style={{ position: 'absolute', left: 2, top: 3, color: 'hsl(240, 14%, 50%)' }}>{icon}</div>
            <span>{text}</span>
        </div>
    )
}
