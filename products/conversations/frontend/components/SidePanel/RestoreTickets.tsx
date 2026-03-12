import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconArrowLeft, IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { sidepanelTicketsLogic } from './sidepanelTicketsLogic'

export function RestoreTickets(): JSX.Element {
    const { restoreState, restoreError } = useValues(sidepanelTicketsLogic)
    const { requestRestoreLink, setView, setRestoreState } = useActions(sidepanelTicketsLogic)
    const [email, setEmail] = useState('')

    if (restoreState === 'sent') {
        return (
            <div className="flex flex-col items-center gap-3 py-8 text-center">
                <IconCheckCircle className="text-success text-4xl" />
                <h3 className="font-semibold text-lg m-0">Check your email</h3>
                <p className="text-sm text-muted-alt m-0 max-w-xs">
                    If we found conversations matching that email, we've sent a recovery link. It expires in 1 hour.
                </p>
                <LemonButton
                    type="secondary"
                    onClick={() => {
                        setRestoreState('idle')
                        setView('list')
                    }}
                >
                    Back to tickets
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
                <LemonButton
                    icon={<IconArrowLeft />}
                    size="small"
                    onClick={() => setView('list')}
                    data-attr="sidebar-go-back-to-tickets"
                />
                <span className="font-semibold">Recover your tickets</span>
            </div>

            <p className="text-sm text-muted-alt m-0">
                Enter the email you used in your previous conversations. We'll send you a link to restore them.
            </p>

            <form
                onSubmit={(e) => {
                    e.preventDefault()
                    if (email.trim()) {
                        requestRestoreLink(email.trim())
                    }
                }}
                className="flex flex-col gap-2"
            >
                <LemonInput
                    type="email"
                    placeholder="you@example.com"
                    value={email}
                    onChange={setEmail}
                    fullWidth
                    autoFocus
                />
                {restoreState === 'error' && restoreError && <p className="text-danger text-sm m-0">{restoreError}</p>}
                <LemonButton
                    type="primary"
                    htmlType="submit"
                    fullWidth
                    center
                    loading={restoreState === 'sending'}
                    disabledReason={!email.trim() ? 'Enter your email address' : undefined}
                >
                    Send recovery link
                </LemonButton>
            </form>
        </div>
    )
}
