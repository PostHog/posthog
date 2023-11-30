import clsx from 'clsx'
import { useValues } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Within3000PageHeaderContext } from 'lib/lemon-ui/LemonButton/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { createPortal } from 'react-dom'
import { DraggableToNotebook, DraggableToNotebookProps } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'

interface PageHeaderProps {
    title: string | JSX.Element
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
    buttons,
    style,
    tabbedPage,
    delimited,
    notebookProps,
}: PageHeaderProps): JSX.Element | null {
    const is3000 = useFeatureFlag('POSTHOG_3000')
    const { actionsContainer } = useValues(breadcrumbsLogic)

    return (
        <>
            {!is3000 && (
                <div className="page-title-row flex justify-between" style={style}>
                    <div className="min-w-0">
                        {!is3000 &&
                            (notebookProps ? (
                                <DraggableToNotebook {...notebookProps}>
                                    <h1 className="page-title">{title}</h1>
                                </DraggableToNotebook>
                            ) : (
                                <h1 className="page-title">{title}</h1>
                            ))}
                    </div>
                    {!is3000 && <div className="page-buttons">{buttons}</div>}
                </div>
            )}
            {is3000 &&
                buttons &&
                actionsContainer &&
                createPortal(
                    <Within3000PageHeaderContext.Provider value={is3000}>
                        {buttons}
                    </Within3000PageHeaderContext.Provider>,
                    actionsContainer
                )}

            {caption && <div className={clsx('page-caption', tabbedPage && 'tabbed')}>{caption}</div>}
            {delimited && <LemonDivider className={is3000 ? 'hidden' : 'my-4'} />}
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
