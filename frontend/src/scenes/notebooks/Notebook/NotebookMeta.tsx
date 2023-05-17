import { NotebookLogicProps, notebookLogic } from './notebookLogic'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useValues } from 'kea'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { useEffect, useState } from 'react'

export const NotebookSyncStatus = (props: NotebookLogicProps): JSX.Element => {
    const { syncStatus } = useValues(notebookLogic(props))

    const [shown, setShown] = useState(false)
    const content =
        syncStatus === 'synced' ? (
            'Saved'
        ) : syncStatus === 'saving' ? (
            <>
                Saving <Spinner monocolor />
            </>
        ) : (
            'Edited'
        )

    useEffect(() => {
        if (syncStatus !== 'synced') {
            return setShown(true)
        }

        if (shown === false) {
            return
        }

        const t = setTimeout(() => setShown(false), 3000)
        return () => clearTimeout(t)
    }, [syncStatus])

    return shown ? (
        <Tooltip title={syncStatus}>
            <span className="flex items-center gap-1 text-muted-alt">{content}</span>
        </Tooltip>
    ) : (
        <></>
    )
}

export function NotebookMeta(props: NotebookLogicProps): JSX.Element {
    const { notebook } = useValues(notebookLogic(props))

    return (
        <div className="flex items-center gap-2">
            <UserActivityIndicator at={notebook?.last_modified_at} by={notebook?.last_modified_by} />
            <NotebookSyncStatus id={props.id} />
        </div>
    )
}
