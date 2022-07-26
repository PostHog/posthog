import { Row } from 'antd'
import clsx from 'clsx'
import React from 'react'
import { LemonDivider } from './LemonDivider'

interface PageHeaderProps {
    title: string | JSX.Element
    caption?: string | JSX.Element | null | false
    buttons?: JSX.Element | false
    style?: React.CSSProperties
    tabbedPage?: boolean // Whether the page has tabs for secondary navigation
    delimited?: boolean
}

export function PageHeader({ title, caption, buttons, style, tabbedPage, delimited }: PageHeaderProps): JSX.Element {
    const row = (
        <div className="page-title-row" style={{ justifyContent: buttons ? 'space-between' : 'start', ...style }}>
            <h1 className="page-title">{title}</h1>
            <div className="page-buttons">{buttons}</div>
        </div>
    )
    return caption || delimited ? (
        <>
            {row}
            <div className={clsx('page-caption', tabbedPage && 'tabbed')}>{caption}</div>
            {delimited && <LemonDivider large />}
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
        <Row className="mt-2" justify={buttons ? 'space-between' : 'start'} align="middle">
            <h2 className="subtitle">{subtitle}</h2>
            {buttons}
        </Row>
    )
}
