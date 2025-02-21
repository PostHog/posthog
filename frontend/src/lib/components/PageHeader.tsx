import clsx from 'clsx'
import { WithinPageHeaderContext } from 'lib/lemon-ui/LemonButton/LemonButton'
import { DraggableToNotebookProps } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'

interface PageHeaderProps {
    caption?: string | JSX.Element | null | false
    buttons?: JSX.Element | false
    tabbedPage?: boolean // Whether the page has tabs for secondary navigation
    delimited?: boolean
    notebookProps?: Pick<DraggableToNotebookProps, 'href' | 'node' | 'properties'>
}

export function PageHeader({ caption, buttons, tabbedPage }: PageHeaderProps): JSX.Element | null {
    if (!caption && !buttons) {
        return null
    }

    return (
        <div className="page-header">
            <div
                className={clsx(
                    'page-header-content',
                    'flex items-center gap-2',
                    caption ? 'justify-between' : 'justify-end'
                )}
            >
                {caption && <div className={clsx('page-caption', tabbedPage && 'tabbed')}>{caption}</div>}
                {buttons && (
                    <div className="page-buttons flex items-center gap-2">
                        <WithinPageHeaderContext.Provider value={true}>{buttons}</WithinPageHeaderContext.Provider>
                    </div>
                )}
            </div>
        </div>
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
