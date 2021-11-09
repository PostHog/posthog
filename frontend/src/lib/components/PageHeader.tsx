import { Row } from 'antd'
import React from 'react'

interface PageHeaderProps {
    title: string | JSX.Element
    caption?: string | JSX.Element
    buttons?: JSX.Element | false
    style?: React.CSSProperties
}

export function PageHeader({ title, caption, buttons, style }: PageHeaderProps): JSX.Element {
    const row = (
        <Row className="page-title-row" justify={buttons ? 'space-between' : 'start'} align="middle" style={style}>
            <h1 className="page-title">{title}</h1>
            {buttons}
        </Row>
    )
    return caption ? (
        <>
            {row}
            <div className="page-caption">{caption}</div>
        </>
    ) : (
        row
    )
}

interface SubtitleProps {
    subtitle: string | JSX.Element
    buttons?: JSX.Element | null | false
}

export function Subtitle({ subtitle, buttons }: SubtitleProps): JSX.Element {
    return (
        <Row className="subtitle-row" justify={buttons ? 'space-between' : 'start'} align="middle">
            <h2 className="subtitle">{subtitle}</h2>
            {buttons}
        </Row>
    )
}
