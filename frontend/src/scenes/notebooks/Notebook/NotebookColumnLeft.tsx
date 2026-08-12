import clsx from 'clsx'
import { useValues } from 'kea'

import { NotebookHistory } from './NotebookHistory'
import { notebookLogic } from './notebookLogic'

export const NotebookColumnLeft = (): JSX.Element | null => {
    const { isShowingLeftColumn, showHistory } = useValues(notebookLogic)

    const isShowingEffectiveLeftColumn = isShowingLeftColumn && showHistory

    return (
        <div
            className={clsx('NotebookColumn NotebookColumn--left', {
                'NotebookColumn--showing': isShowingEffectiveLeftColumn,
            })}
        >
            <div className="NotebookColumn__content">{isShowingEffectiveLeftColumn ? <NotebookHistory /> : null}</div>
        </div>
    )
}
