import './NotFound.scss'

import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconArrowRight, IconCheckCircle } from '@posthog/icons'
import { LemonButton, ProfilePicture, SpinnerOverlay, lemonToast } from '@posthog/lemon-ui'

import { getCookie } from 'lib/api'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { Link } from 'lib/lemon-ui/Link'
import { capitalizeFirstLetter } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { getAppContext } from 'lib/utils/getAppContext'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { getDefaultEventsSceneQuery } from 'scenes/activity/explore/defaults'
import { useNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'
import { urls } from 'scenes/urls'

import { ActivityTab, PropertyFilterType, PropertyOperator, UserBasicType } from '~/types'

import { ScrollableShadows } from '../ScrollableShadows/ScrollableShadows'
import { supportLogic } from '../Support/supportLogic'

interface NotFoundProps {
    // Type of object that was not found (e.g. `dashboard`, `insight`, `action`, ...)
    object: string
    caption?: React.ReactNode
    meta?: {
        urlId?: string
    }
    className?: string
}

export function NotFound({ object, caption, meta, className }: NotFoundProps): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { openSupportForm } = useActions(supportLogic)

    const nodeLogic = useNotebookNode()

    const appContext = getAppContext()

    useOnMountEffect(() => {
        posthog.capture('not_found_shown', { object })
    })

    return (
        <div
            className={cn('NotFoundComponent', className)}
            data-attr={`not-found-${object.replace(/\s/g, '-').toLowerCase()}`}
        >
            {!nodeLogic ? <div className="NotFoundComponent__graphic" /> : null}
            <h1 className="text-2xl font-bold mt-4 mb-0">
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
            {object === 'Person' && meta?.urlId && (
                <div className="flex justify-center mt-4 w-fit">
                    <LemonButton
                        type="secondary"
                        size="small"
                        tooltip={`View events matching distinct_id=${meta?.urlId}`}
                        to={
                            combineUrl(
                                urls.activity(ActivityTab.ExploreEvents),
                                {},
                                {
                                    q: getDefaultEventsSceneQuery([
                                        {
                                            type: PropertyFilterType.EventMetadata,
                                            key: 'distinct_id',
                                            value: meta.urlId,
                                            operator: PropertyOperator.Exact,
                                        },
                                    ]),
                                }
                            ).url
                        }
                    >
                        View events
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
        <ScrollableShadows direction="vertical" className="bg-surface-primary border rounded mt-1 max-h-64 *:p-1">
            <LemonMenuOverlay
                items={suggestedUsers.map((user) => ({
                    icon: <ProfilePicture user={user} size="md" />,
                    label: `${user.first_name} ${user.last_name} (${user.email})`,
                    tooltip: `Log in as ${user.first_name}`,
                    sideIcon: user.id === successfulUserId ? <IconCheckCircle /> : <IconArrowRight />,
                    onClick: async () => {
                        setIsLoginInProgress(true)

                        try {
                            // check if admin OAuth2 verification is needed
                            const authCheckResponse = await fetch('/admin/auth_check', {
                                method: 'GET',
                                credentials: 'same-origin',
                                redirect: 'manual',
                            })

                            if (!authCheckResponse.ok) {
                                // Need OAuth2 verification - open a popup
                                const width = 600
                                const height = 700
                                const left = window.screen.width / 2 - width / 2
                                const top = window.screen.height / 2 - height / 2

                                const authWindow = window.open(
                                    '/admin/oauth2/success', // This will redirect to OAuth2
                                    'admin_oauth2',
                                    `width=${width},height=${height},top=${top},left=${left},toolbar=no,location=no,directories=no,status=no,menubar=no,scrollbars=yes,resizable=yes`
                                )

                                // Wait for the OAuth2 completion message
                                await new Promise<void>((resolve) => {
                                    const handleMessage = (event: MessageEvent): void => {
                                        if (event.origin !== window.location.origin) {
                                            return
                                        }
                                        if (event.data?.type === 'oauth2_complete') {
                                            window.removeEventListener('message', handleMessage)
                                            resolve()
                                        }
                                    }
                                    window.addEventListener('message', handleMessage)

                                    // Also poll to check if the window was closed manually
                                    const checkClosed = setInterval(() => {
                                        if (authWindow?.closed) {
                                            clearInterval(checkClosed)
                                            window.removeEventListener('message', handleMessage)
                                            resolve()
                                        }
                                    }, 500)
                                })
                            }

                            // Now proceed with the login-as request
                            const loginResponse = await fetch(`/admin/login/user/${user.id}/`, {
                                method: 'POST',
                                credentials: 'same-origin',
                                mode: 'cors',
                                headers: {
                                    'X-CSRFToken': getCookie('posthog_csrftoken') as string,
                                },
                            })

                            if (!loginResponse.ok) {
                                throw new Error(`django-loginas request resulted in status ${loginResponse.status}`)
                            }

                            setSuccessfulUserId(user.id)
                            window.location.reload()
                        } catch {
                            lemonToast.error(`Failed to log in as ${user.first_name}`)
                            setIsLoginInProgress(false) // Only set to false if we aren't about to reload the page
                        }
                    },
                }))}
                tooltipPlacement="right"
                buttonSize="medium"
            />
            {isLoginInProgress && <SpinnerOverlay className="text-3xl" />}
        </ScrollableShadows>
    )
}
