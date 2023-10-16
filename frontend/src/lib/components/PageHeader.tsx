import clsx from 'clsx'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { DraggableToNotebook, DraggableToNotebookProps } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'

interface PageHeaderProps {
    title: string | JSX.Element
    description?: string | JSX.Element
    caption?: string | JSX.Element | null | false
    buttons?: JSX.Element | false
    style?: React.CSSProperties
    tabbedPage?: boolean // Whether the page has tabs for secondary navigation
    delimited?: boolean
    notebookProps?: Pick<DraggableToNotebookProps, 'href' | 'node' | 'properties'>
}

export function PageHeader({
    title,
    caption,
    description,
    buttons,
    style,
    tabbedPage,
    delimited,
    notebookProps,
}: PageHeaderProps): JSX.Element {
    return (
        <>
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div className="page-title-row flex justify-between" style={style}>
                <div className="min-w-0">
                    {notebookProps ? (
                        <DraggableToNotebook {...notebookProps}>
                            <h1 className="page-title">{title}</h1>
                        </DraggableToNotebook>
                    ) : (
                        <h1 className="page-title">{title}</h1>
                    )}
                    <span className="page-description">{description}</span>
                </div>
                <div className="page-buttons">{buttons}</div>
            </div>

            {caption && <div className={clsx('page-caption', tabbedPage && 'tabbed')}>{caption}</div>}
            {delimited && <LemonDivider className="my-4" />}
        </>
    )
}

interface SubtitleProps {
    subtitle: string | JSX.Element
    buttons?: JSX.Element | null | false
}

export function Subtitle({ subtitle, buttons }: SubtitleProps): JSX.Element {
    return (
        <div className={clsx('flex mt-5 items-center', buttons ? 'justify-between' : 'justify-start')}>
            <h2 className="subtitle">{subtitle}</h2>
            {buttons}
        </div>
    )
}
