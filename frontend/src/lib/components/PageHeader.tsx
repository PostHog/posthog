import { Row } from 'antd'
import clsx from 'clsx'
import React from 'react'

interface PageHeaderProps {
    title: string | JSX.Element
    caption?: string | JSX.Element
    buttons?: JSX.Element | false
    style?: React.CSSProperties
    tabbedPage?: boolean // Whether the page has tabs for secondary navigation
}

export function PageHeader({ title, caption, buttons, style, tabbedPage }: PageHeaderProps): JSX.Element {
    const row = (
        <Row className="page-title-row" justify={buttons ? 'space-between' : 'start'} align="middle" style={style}>
            <h1 className="page-title">{title}</h1>
            {buttons}
        </Row>
    )
    return caption ? (
        <>
            {row}
            <div className={clsx('page-caption', tabbedPage && 'tabbed')}>{caption}</div>
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
