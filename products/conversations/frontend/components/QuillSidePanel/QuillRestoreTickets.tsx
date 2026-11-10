import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconArrowLeft, IconCheckCircle } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Field,
    FieldError,
    FieldLabel,
    Heading,
    Input,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { sidepanelTicketsLogic } from '../SidePanel/sidepanelTicketsLogic'

export function QuillRestoreTickets(): JSX.Element {
    const { restoreState, restoreError } = useValues(sidepanelTicketsLogic)
    const { requestRestoreLink, setView, setRestoreState } = useActions(sidepanelTicketsLogic)
    const [email, setEmail] = useState('')

    if (restoreState === 'sent') {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconCheckCircle />
                    </EmptyMedia>
                    <EmptyTitle>Check your email</EmptyTitle>
                    <EmptyDescription>
                        If we found conversations matching that email, we've sent a recovery link. It expires in 1 hour.
                    </EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                    <Button
                        variant="outline"
                        onClick={() => {
                            setRestoreState('idle')
                            setView('list')
                        }}
                    >
                        Back to tickets
                    </Button>
                </EmptyContent>
            </Empty>
        )
    }

    const trimmedEmail = email.trim()

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
                <Tooltip>
                    <TooltipTrigger
                        delay={0}
                        render={
                            <Button
                                size="icon"
                                aria-label="Back to tickets"
                                onClick={() => setView('list')}
                                data-attr="sidebar-go-back-to-tickets"
                            />
                        }
                    >
                        <IconArrowLeft />
                    </TooltipTrigger>
                    <TooltipContent>Back to tickets</TooltipContent>
                </Tooltip>
                <Heading size="sm" render={<h3 className="m-0" />}>
                    Recover your tickets
                </Heading>
            </div>
            <Text size="xs" variant="muted">
                Enter the email you used in your previous conversations. We'll send you a link to restore them.
            </Text>
            <form
                className="flex flex-col gap-3"
                onSubmit={(event) => {
                    event.preventDefault()
                    if (trimmedEmail) {
                        requestRestoreLink(trimmedEmail)
                    }
                }}
            >
                <Field>
                    <FieldLabel htmlFor="support-restore-email">Email</FieldLabel>
                    <Input
                        id="support-restore-email"
                        type="email"
                        placeholder="you@example.com"
                        value={email}
                        onChange={(event: React.ChangeEvent<HTMLInputElement>) => setEmail(event.target.value)}
                        autoFocus
                    />
                    {restoreState === 'error' && restoreError && <FieldError>{restoreError}</FieldError>}
                </Field>
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <Button
                                type="submit"
                                variant="primary"
                                loading={restoreState === 'sending'}
                                disabled={!trimmedEmail}
                            />
                        }
                    >
                        Send recovery link
                    </TooltipTrigger>
                    {!trimmedEmail && <TooltipContent>Enter your email address</TooltipContent>}
                </Tooltip>
            </form>
        </div>
    )
}
