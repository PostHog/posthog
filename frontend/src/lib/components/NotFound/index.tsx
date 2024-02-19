import './NotFound.scss'

import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/lemon-ui/Link'
import { capitalizeFirstLetter } from 'lib/utils'
import { useNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { supportLogic } from '../Support/supportLogic'

interface NotFoundProps {
    object: string // Type of object that was not found (e.g. `dashboard`, `insight`, `action`, ...)
    caption?: React.ReactNode
}

export function NotFound({ object, caption }: NotFoundProps): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { openSupportForm } = useActions(supportLogic)

    const nodeLogic = useNotebookNode()

    return (
        <div className="NotFoundComponent">
            {!nodeLogic ? <div className="NotFoundComponent__graphic" /> : null}
            <h1 className="text-3xl font-bold mt-4 mb-0">{capitalizeFirstLetter(object)} not found</h1>
            {!nodeLogic ? <p className="text-sm font-semibold italic mt-3 mb-0">It might be lost in space.</p> : null}
            <p className="text-sm mt-3 mb-0">
                {caption || (
                    <>
                        It's possible this {object} has been deleted or its sharing settings have changed.
                        <br />
                        Please check with the person who sent you here
                        {preflight?.cloud ? (
                            <>
                                , or <Link onClick={() => openSupportForm({ kind: 'support' })}>contact support</Link>{' '}
                                if you think this is a mistake
                            </>
                        ) : null}
                        .
                    </>
                )}
            </p>
            {nodeLogic && (
                <div className="flex justify-center mt-4">
                    <LemonButton type="secondary" status="danger" onClick={nodeLogic.actions.deleteNode}>
                        Remove from Notebook
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
