import './ImpersonationNotice.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'

import { IconCollapse, IconEllipsis, IconWarning } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonMenu, Spinner, Tooltip } from '@posthog/lemon-ui'

import { DraggableWithSnapZones, DraggableWithSnapZonesRef, SnapPosition } from 'lib/components/DraggableWithSnapZones'
import { dayjs } from 'lib/dayjs'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { IconDragHandle } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'
import { userLogic } from 'scenes/userLogic'

import { ImpersonationTicketContext, TicketMessage, impersonationNoticeLogic } from './impersonationNoticeLogic'
import { ImpersonationReasonModal } from './ImpersonationReasonModal'

function CountDown({ datetime, callback }: { datetime: dayjs.Dayjs; callback?: () => void }): JSX.Element {
    const [now, setNow] = useState(() => dayjs())
    const { isVisible: isPageVisible } = usePageVisibility()

    const duration = dayjs.duration(datetime.diff(now))
    const pastCountdown = duration.seconds() < 0

    const countdown = pastCountdown
        ? 'Expired'
        : duration.hours() > 0
          ? duration.format('HH:mm:ss')
          : duration.format('mm:ss')

    useEffect(() => {
        if (!isPageVisible) {
            return
        }

        setNow(dayjs())
        const interval = setInterval(() => setNow(dayjs()), 1000)
        return () => clearInterval(interval)
    }, [isPageVisible])

    useEffect(() => {
        if (pastCountdown) {
            callback?.() // oxlint-disable-line react-hooks/exhaustive-deps
        }
    }, [pastCountdown])

    return <span className="tabular-nums text-warning">{countdown}</span>
}

function TicketMessageBubble({ message }: { message: TicketMessage }): JSX.Element {
    const isCustomer = message.authorType === 'customer'

    return (
        <div className={cn('flex flex-col gap-0.5', isCustomer ? 'items-start' : 'items-end')}>
            <div className="flex items-center gap-1 text-[10px] text-muted-alt px-1">
                <span>{message.authorName}</span>
                <span>·</span>
                <span>{dayjs(message.createdAt).format('MMM D, h:mm A')}</span>
                {message.isPrivate && <span className="text-warning-dark">(private)</span>}
            </div>
            <div
                className={cn(
                    'rounded-lg px-2 py-1 text-xs max-w-[85%]',
                    isCustomer ? 'bg-surface-tertiary' : 'bg-primary-highlight'
                )}
            >
                {message.content}
            </div>
        </div>
    )
}

function TicketMessagesContent({ messages, loading }: { messages: TicketMessage[]; loading: boolean }): JSX.Element {
    const messagesEndRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, [messages.length])

    return (
        <div
            className="overflow-y-auto space-y-2 bg-surface-primary rounded p-2"
            style={{ height: '25vh', maxHeight: '300px' }}
        >
            {loading ? (
                <div className="flex items-center justify-center h-full">
                    <Spinner />
                </div>
            ) : messages.length === 0 ? (
                <div className="flex items-center justify-center h-full text-muted-alt text-xs">No messages yet</div>
            ) : (
                <>
                    {messages.map((message) => (
                        <TicketMessageBubble key={message.id} message={message} />
                    ))}
                    <div ref={messagesEndRef} />
                </>
            )}
        </div>
    )
}

function getPersistedSnapPosition(): SnapPosition | null {
    try {
        const stored = localStorage.getItem('impersonation-notice-position')
        if (stored) {
            const parsed = JSON.parse(stored)
            return parsed.snapPosition || null
        }
    } catch {
        // Ignore
    }
    return null
}

function isPositionOnRight(position: SnapPosition | null): boolean {
    return position?.includes('right') ?? true
}

function LoginAsContent({ ticketContext }: { ticketContext: ImpersonationTicketContext }): JSX.Element {
    const { initiateImpersonation } = useActions(impersonationNoticeLogic)

    const disabledReason = !ticketContext.email
        ? 'This ticket has no associated email'
        : !ticketContext.region
          ? 'Unable to determine region for this ticket, no login available'
          : undefined

    return (
        <>
            <p className="ImpersonationNotice__message">
                {ticketContext.email ? (
                    <>
                        Customer: <span className="text-success">{ticketContext.email}</span>
                    </>
                ) : (
                    'No customer email on this ticket'
                )}
            </p>
            <div className="flex gap-2 justify-end">
                <LemonButton
                    type="secondary"
                    size="small"
                    disabledReason={disabledReason}
                    onClick={() => initiateImpersonation()}
                >
                    Login as {ticketContext.email || 'customer'}
                </LemonButton>
            </div>
        </>
    )
}

function ImpersonationNoticeContent(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { logout, loadUser } = useActions(userLogic)
    const {
        isUpgradeModalOpen,
        isImpersonationUpgradeInProgress,
        impersonationTicket,
        ticketMessages,
        ticketMessagesLoading,
        isTicketExpanded,
    } = useValues(impersonationNoticeLogic)
    const { closeUpgradeModal, upgradeImpersonation, toggleTicketExpanded } = useActions(impersonationNoticeLogic)

    return (
        <>
            <p className="ImpersonationNotice__message">
                Signed in as <span className="text-warning">{user?.email}</span>
                {user?.organization?.name && (
                    <>
                        {' '}
                        from <span className="text-warning">{user.organization.name}</span>
                    </>
                )}
                .
                {user?.is_impersonated_until && (
                    <>
                        {' '}
                        Expires in <CountDown datetime={dayjs(user.is_impersonated_until)} callback={loadUser} />.
                    </>
                )}
            </p>
            {impersonationTicket && (
                <LemonCollapse
                    panels={[
                        {
                            key: 'ticket',
                            header: `Working on Ticket #${impersonationTicket.ticket_number}`,
                            content: (
                                <TicketMessagesContent messages={ticketMessages} loading={ticketMessagesLoading} />
                            ),
                        },
                    ]}
                    activeKey={isTicketExpanded ? 'ticket' : undefined}
                    onChange={(key) => {
                        if ((key === 'ticket') !== isTicketExpanded) {
                            toggleTicketExpanded()
                        }
                    }}
                    size="small"
                    embedded
                />
            )}
            <div className="flex gap-2 justify-end">
                <LemonButton type="secondary" size="small" onClick={() => loadUser()} loading={userLoading}>
                    Refresh
                </LemonButton>
                <LemonButton type="secondary" status="danger" size="small" onClick={() => logout()}>
                    Log out
                </LemonButton>
            </div>
            {isUpgradeModalOpen && (
                <ImpersonationReasonModal
                    isOpen
                    onClose={closeUpgradeModal}
                    onConfirm={upgradeImpersonation}
                    title="Upgrade to read-write impersonation"
                    description="Read-write mode allows you to make changes on behalf of the user. Please provide a reason for this upgrade."
                    defaultReason={
                        impersonationTicket ? `Investigating Ticket #${impersonationTicket.ticket_number}` : ''
                    }
                    confirmText="Upgrade"
                    loading={isImpersonationUpgradeInProgress}
                />
            )}
        </>
    )
}

export function ImpersonationNotice(): JSX.Element | null {
    const { user } = useValues(userLogic)

    const { isMinimized, isReadOnly, isImpersonated, isTicketExpanded, ticketContext } =
        useValues(impersonationNoticeLogic)
    const { minimize, maximize, openUpgradeModal, setPageVisible } = useActions(impersonationNoticeLogic)

    const { isVisible: isPageVisible } = usePageVisibility()

    const draggableRef = useRef<DraggableWithSnapZonesRef>(null)
    const [isDragging, setIsDragging] = useState(false)

    // Track snap position for determining expansion direction
    const [snapPosition, setSnapPosition] = useState<SnapPosition | null>(() => getPersistedSnapPosition())

    const handleMinimize = (): void => {
        minimize()
        draggableRef.current?.trySnapTo('bottom-right')
    }

    const handleDragStop = (): void => {
        setIsDragging(false)
        // Update snap position from localStorage after drag
        setSnapPosition(getPersistedSnapPosition())
    }

    useEffect(() => {
        setPageVisible(isPageVisible)
    }, [isPageVisible, setPageVisible])

    // Determine if the panel should expand to the left based on position
    const expandsLeft = useMemo(() => isPositionOnRight(snapPosition), [snapPosition])

    const showLoginAs = user?.is_staff && !isImpersonated && !!ticketContext

    if (!user || (!isImpersonated && !showLoginAs)) {
        return null
    }

    const title = showLoginAs ? 'Staff actions' : isReadOnly ? 'Read-only impersonation' : 'Read-write impersonation'

    return (
        <DraggableWithSnapZones
            ref={draggableRef}
            handle=".ImpersonationNotice__sidebar"
            defaultSnapPosition="bottom-right"
            persistKey="impersonation-notice-position"
            onDragStart={() => setIsDragging(true)}
            onDragStop={handleDragStop}
        >
            <div
                className={cn(
                    'ImpersonationNotice',
                    isDragging && 'ImpersonationNotice--dragging',
                    isMinimized && 'ImpersonationNotice--minimized',
                    showLoginAs
                        ? 'ImpersonationNotice--login-as'
                        : isReadOnly
                          ? 'ImpersonationNotice--read-only'
                          : 'ImpersonationNotice--read-write',
                    isTicketExpanded && 'ImpersonationNotice--ticket-expanded',
                    isTicketExpanded && expandsLeft && 'ImpersonationNotice--expands-left'
                )}
            >
                <div className="ImpersonationNotice__sidebar">
                    <IconDragHandle className="ImpersonationNotice__drag-handle" />
                </div>
                {isMinimized && (
                    <Tooltip
                        title={
                            showLoginAs
                                ? 'Staff actions - click to expand'
                                : 'Signed in as a customer - click to expand'
                        }
                    >
                        <div className="ImpersonationNotice__minimized-content" onClick={maximize}>
                            <IconWarning className="ImpersonationNotice__minimized-icon" />
                        </div>
                    </Tooltip>
                )}
                {!isMinimized && (
                    <div className="ImpersonationNotice__main">
                        <div className="ImpersonationNotice__header">
                            <IconWarning className="ImpersonationNotice__warning-icon" />
                            <span className="ImpersonationNotice__title">{title}</span>
                            {isImpersonated && isReadOnly && (
                                <LemonMenu
                                    items={[
                                        {
                                            label: 'Upgrade to read-write',
                                            onClick: openUpgradeModal,
                                        },
                                    ]}
                                >
                                    <LemonButton size="xsmall" icon={<IconEllipsis />} />
                                </LemonMenu>
                            )}
                            <LemonButton size="xsmall" icon={<IconCollapse />} onClick={handleMinimize} />
                        </div>
                        <div className="ImpersonationNotice__content">
                            {showLoginAs ? (
                                <LoginAsContent ticketContext={ticketContext!} />
                            ) : (
                                <ImpersonationNoticeContent />
                            )}
                        </div>
                    </div>
                )}
            </div>
        </DraggableWithSnapZones>
    )
}
