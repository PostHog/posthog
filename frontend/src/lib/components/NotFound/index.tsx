import './NotFound.scss'

import { IconArrowRight, IconCheckCircle } from '@posthog/icons'
import { LemonButton, lemonToast, ProfilePicture, SpinnerOverlay } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { getCookie } from 'lib/api'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { Link } from 'lib/lemon-ui/Link'
import { capitalizeFirstLetter } from 'lib/utils'
import { getAppContext } from 'lib/utils/getAppContext'
import { useState } from 'react'
import { useNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { UserBasicType } from '~/types'

import { ScrollableShadows } from '../ScrollableShadows/ScrollableShadows'
import { supportLogic } from '../Support/supportLogic'

interface NotFoundProps {
    object: string // Type of object that was not found (e.g. `dashboard`, `insight`, `action`, ...)
    caption?: React.ReactNode
}

export function NotFound({ object, caption }: NotFoundProps): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { openSupportForm } = useActions(supportLogic)

    const nodeLogic = useNotebookNode()

    const appContext = getAppContext()

    return (
        <div className="NotFoundComponent">
            {!nodeLogic ? <div className="NotFoundComponent__graphic" /> : null}
            <h1 className="text-3xl font-bold mt-4 mb-0">
                {appContext?.suggested_users_with_access
                    ? 'Log in as a customer to access this project'
                    : `${capitalizeFirstLetter(object)} not found`}
            </h1>
            {!nodeLogic ? (
                <p className="text-sm font-semibold italic mt-3 mb-0">
                    {appContext?.suggested_users_with_access ? (
                        <>
                            The user
                            {appContext.suggested_users_with_access.length === 1
                                ? ' below is the only one with'
                                : 's below have'}{' '}
                            relevant access.
                            <br />
                            You're seeing this, because you're a staff user.
                        </>
                    ) : (
                        'It might be lost in space.'
                    )}
                </p>
            ) : null}
            <p className="text-sm mt-3 mb-0">
                {appContext?.suggested_users_with_access ? (
                    <LogInAsSuggestions suggestedUsers={appContext.suggested_users_with_access} />
                ) : (
                    caption || (
                        <>
                            It's possible this {object} has been deleted or its sharing settings have changed.
                            <br />
                            Please check with the person who sent you here
                            {preflight?.cloud ? (
                                <>
                                    , or{' '}
                                    <Link onClick={() => openSupportForm({ kind: 'support' })}>contact support</Link> if
                                    you think this is a mistake
                                </>
                            ) : null}
                            .
                        </>
                    )
                )}
            </p>
            {nodeLogic && (
                <div className="flex justify-center mt-4 w-fit">
                    <LemonButton type="secondary" status="danger" onClick={nodeLogic.actions.deleteNode}>
                        Remove from Notebook
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

export function LogInAsSuggestions({ suggestedUsers }: { suggestedUsers: UserBasicType[] }): JSX.Element {
    const [isLoginInProgress, setIsLoginInProgress] = useState(false)
    const [successfulUserId, setSuccessfulUserId] = useState<number | null>(null)

    return (
        <ScrollableShadows direction="vertical" className="bg-bg-light border rounded mt-1 max-h-64 *:p-1">
            <LemonMenuOverlay
                items={suggestedUsers.map((user) => ({
                    icon: <ProfilePicture user={user} size="md" />,
                    label: `${user.first_name} ${user.last_name} (${user.email})`,
                    tooltip: `Log in as ${user.first_name}`,
                    sideIcon: user.id === successfulUserId ? <IconCheckCircle /> : <IconArrowRight />,
                    onClick: () => {
                        setIsLoginInProgress(true)
                        fetch(`/admin/login/user/${user.id}/`, {
                            method: 'POST',
                            credentials: 'same-origin',
                            mode: 'cors',
                            headers: {
                                'X-CSRFToken': getCookie('posthog_csrftoken') as string,
                            },
                        })
                            .then((response) => {
                                if (response.status !== 200) {
                                    throw new Error(`django-loginas request resulted in status ${response.status}`)
                                }
                                setSuccessfulUserId(user.id)
                                window.location.reload()
                            })
                            .catch(() => {
                                lemonToast.error(`Failed to log in as ${user.first_name}`)
                                setIsLoginInProgress(false) // Only set to false if we aren't about to reload the page
                            })
                    },
                }))}
                tooltipPlacement="right"
                buttonSize="medium"
            />
            {isLoginInProgress && <SpinnerOverlay className="text-3xl" />}
        </ScrollableShadows>
    )
}
