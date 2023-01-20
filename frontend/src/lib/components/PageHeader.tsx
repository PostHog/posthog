import { Row } from 'antd'
import clsx from 'clsx'
import { LemonDivider } from './LemonDivider'

interface PageHeaderProps {
    title: string | JSX.Element
    description?: string | JSX.Element
    caption?: string | JSX.Element | null | false
    buttons?: JSX.Element | false
    style?: React.CSSProperties
    tabbedPage?: boolean // Whether the page has tabs for secondary navigation
    delimited?: boolean
}

export function PageHeader({
    title,
    caption,
    description,
    buttons,
    style,
    tabbedPage,
    delimited,
}: PageHeaderProps): JSX.Element {
    const row = (
        <div className="page-title-row flex justify-between" style={style}>
            <div>
                <h1 className="page-title">{title}</h1>
                <span className="page-description">{description}</span>
            </div>
            <div className="page-buttons">{buttons}</div>
        </div>
    )
    return caption || delimited ? (
        <>
            {row}
            <div className={clsx('page-caption', tabbedPage && 'tabbed')}>{caption}</div>
            {delimited && <LemonDivider className="my-4" />}
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
        <Row className="mt-8" justify={buttons ? 'space-between' : 'start'} align="middle">
            <h2 className="subtitle">{subtitle}</h2>
            {buttons}
        </Row>
    )
}
