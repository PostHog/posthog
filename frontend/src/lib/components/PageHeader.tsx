import clsx from 'clsx'
import { useValues } from 'kea'
import { WithinPageHeaderContext } from 'lib/lemon-ui/LemonButton/LemonButton'
import { createPortal } from 'react-dom'
import { DraggableToNotebookProps } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'

interface PageHeaderProps {
    caption?: string | JSX.Element | null | false
    buttons?: JSX.Element | false
    tabbedPage?: boolean // Whether the page has tabs for secondary navigation
    delimited?: boolean
    notebookProps?: Pick<DraggableToNotebookProps, 'href' | 'node' | 'properties'>
}

export function PageHeader({ caption, buttons, tabbedPage }: PageHeaderProps): JSX.Element | null {
    const { actionsContainer } = useValues(breadcrumbsLogic)

    return (
        <>
            {buttons &&
                actionsContainer &&
                createPortal(
                    <WithinPageHeaderContext.Provider value={true}>{buttons}</WithinPageHeaderContext.Provider>,
                    actionsContainer
                )}

            {caption && <div className={clsx('page-caption', tabbedPage && 'tabbed')}>{caption}</div>}
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
