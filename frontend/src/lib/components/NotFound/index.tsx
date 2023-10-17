import { capitalizeFirstLetter } from 'lib/utils'
import { Link } from 'lib/lemon-ui/Link'
import './NotFound.scss'
import { useActions, useValues } from 'kea'
import { supportLogic } from '../Support/supportLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { useNotebookNode } from 'scenes/notebooks/Nodes/notebookNodeLogic'
import { LemonButton } from '@posthog/lemon-ui'

interface NotFoundProps {
    object: string // Type of object that was not found (e.g. `dashboard`, `insight`, `action`, ...)
    caption?: React.ReactNode
}

export function NotFound({ object, caption }: NotFoundProps): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { openSupportForm } = useActions(supportLogic)

    const nodeLogic = useNotebookNode()

    return (
        <div className="NotFoundComponent space-y-2">
            {!nodeLogic ? <div className="NotFoundComponent__graphic" /> : null}
            <h1>{capitalizeFirstLetter(object)} not found</h1>
            {!nodeLogic ? (
                <p>
                    <b>It seems this {object} may have been lost in space.</b>
                </p>
            ) : null}

            <p>
                {caption || (
                    <>
                        It's possible this {object} may have been deleted or its sharing settings changed. Please check
                        with the person who sent you here
                        {preflight?.cloud ? (
                            <>
                                , or <Link onClick={() => openSupportForm('support')}>contact support</Link> if you
                                think this is a mistake
                            </>
                        ) : null}
                        .
                    </>
                )}
            </p>
            <div className="flex justify-center">
                {nodeLogic && (
                    <LemonButton type="primary" status="danger" onClick={() => nodeLogic.actions.deleteNode()}>
                        Remove from Notebook
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
