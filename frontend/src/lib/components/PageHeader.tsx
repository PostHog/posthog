import clsx from 'clsx'
import { useValues } from 'kea'
import { WithinPageHeaderContext } from 'lib/lemon-ui/LemonButton/LemonButton'
import { useContext } from 'react'
import { createPortal } from 'react-dom'
import { DraggableToNotebookProps } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { WithinSidePanelContext } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'

interface PageHeaderProps {
    caption?: string | JSX.Element | null | false
    buttons?: JSX.Element | false
    tabbedPage?: boolean // Whether the page has tabs for secondary navigation
    delimited?: boolean
    notebookProps?: Pick<DraggableToNotebookProps, 'href' | 'node' | 'properties'>
    className?: string
}

export function PageHeader({ caption, buttons, tabbedPage, className }: PageHeaderProps): JSX.Element | null {
    const { actionsContainer } = useValues(breadcrumbsLogic)

    const withinSidePanel = useContext(WithinSidePanelContext)

    return (
        <>
            {buttons &&
                actionsContainer &&
                !withinSidePanel && // Do not interfere with the main scene if we're only in a side panel here
                createPortal(
                    <WithinPageHeaderContext.Provider value={true}>{buttons}</WithinPageHeaderContext.Provider>,
                    actionsContainer
                )}

            {caption && <div className={clsx('page-caption', tabbedPage && 'tabbed', className)}>{caption}</div>}
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
