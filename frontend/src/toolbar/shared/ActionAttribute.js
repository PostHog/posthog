import React from 'react'
import { FontSizeOutlined, LinkOutlined, FormOutlined, CodeOutlined } from '@ant-design/icons'

export function ActionAttribute({ attribute, value }) {
    const icon =
        attribute === 'text' ? (
            <FontSizeOutlined />
        ) : attribute === 'href' ? (
            <LinkOutlined />
        ) : attribute === 'selector' ? (
            <CodeOutlined />
        ) : (
            <FormOutlined />
        )

    const text =
        attribute === 'href' ? (
            <a href={value} target="_blank" rel="noopener noreferrer">
                {value}
            </a>
        ) : attribute === 'selector' ? (
            <span style={{ fontFamily: 'monospace' }}>{value}</span>
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
