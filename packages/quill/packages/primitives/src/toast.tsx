import './toast.css'

import { Toast } from '@base-ui/react/toast'
import { CircleCheckIcon, InfoIcon, XIcon, TriangleAlertIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from './button'
import { cn } from './lib/utils'
import { Spinner } from './spinner'

// ── Global manager ────────────────────────────────────────────────────
type ToastAction = {
    label: string
    onClick: () => void
}

type ToastActionData = {
    action?: ToastAction
    secondaryAction?: ToastAction
    onDismiss?: () => void
}

const toastManager = Toast.createToastManager<ToastActionData>()
const anchoredToastManager = Toast.createToastManager<ToastActionData>()

// ── Types ─────────────────────────────────────────────────────────────
type ToastType = 'success' | 'info' | 'warning' | 'error' | 'loading'

type ToastOptions = {
    title?: React.ReactNode
    description?: React.ReactNode
    type?: ToastType
    timeout?: number
    onClose?: () => void
    action?: ToastAction
    secondaryAction?: ToastAction
    /** Runs when the user closes the toast with its close button, not when it times out. */
    onDismiss?: () => void
}

// ── Icon map ──────────────────────────────────────────────────────────
const toastIconMap: Record<ToastType, React.ReactNode> = {
    success: <CircleCheckIcon className="quill-toast-card__icon--success size-6" />,
    info: <InfoIcon className="quill-toast-card__icon--info size-6" />,
    warning: <TriangleAlertIcon className="quill-toast-card__icon--warning size-6" />,
    error: <XIcon className="quill-toast-card__icon--error size-6" />,
    loading: <Spinner className="quill-toast-card__icon--loading size-6" />,
}

// ── ToastCard ─────────────────────────────────────────────────────────
type ToastCardProps = React.ComponentPropsWithRef<'div'> & {
    toastTitle?: React.ReactNode
    toastDescription?: React.ReactNode
    icon?: React.ReactNode
    action?: ToastAction
    secondaryAction?: ToastAction
    onDismiss?: () => void
    /** Covers the gap between expanded cards so hovering it keeps the stack open. */
    showGapHitArea?: 'above' | 'below'
}

const ToastCard = React.forwardRef<HTMLDivElement, ToastCardProps>(
    (
        {
            className,
            toastTitle,
            toastDescription,
            icon,
            action,
            secondaryAction,
            onDismiss,
            showGapHitArea,
            children,
            ...props
        },
        ref
    ) => {
        const onlyTitle = toastTitle !== undefined && toastDescription === undefined
        const onlyDescription = toastDescription !== undefined && toastTitle === undefined
        return (
            <div ref={ref} className={cn('quill-toast-card', className)} {...props}>
                {showGapHitArea && (
                    <span
                        className={cn(
                            'pointer-events-auto absolute left-0 w-full',
                            showGapHitArea === 'above' ? 'bottom-full' : 'top-full'
                        )}
                        style={{ height: 'calc(var(--gap) + 1px)' }}
                    />
                )}
                <div className={cn('flex items-center gap-3', onDismiss && 'pe-8')}>
                    {icon && (
                        <span className={cn('shrink-0 self-start mt-1', !toastTitle && toastDescription && 'mt-0')}>
                            {icon}
                        </span>
                    )}
                    <div className="flex-1 min-w-0">
                        {toastTitle && (
                            <div className="quill-toast-card__title" data-base-ui-swipe-ignore>
                                {toastTitle}
                            </div>
                        )}
                        {toastDescription && (
                            <div className="quill-toast-card__description" data-base-ui-swipe-ignore>
                                {toastDescription}
                            </div>
                        )}
                    </div>
                </div>
                {(action || secondaryAction) && (
                    <div className="flex items-center gap-2 mt-2">
                        {icon && <span className="size-6 shrink-0 me-1" />}
                        {action && (
                            <Button variant="outline" onClick={action.onClick}>
                                {action.label}
                            </Button>
                        )}
                        {secondaryAction && (
                            <Button variant="outline" onClick={secondaryAction.onClick}>
                                {secondaryAction.label}
                            </Button>
                        )}
                    </div>
                )}
                {onDismiss && (
                    <Button
                        size="icon-sm"
                        className={cn(
                            'absolute right-2',
                            (onlyTitle && 'top-1') || (onlyDescription && 'top-1') || 'top-2'
                        )}
                        onClick={onDismiss}
                    >
                        <XIcon className="size-3.5" />
                    </Button>
                )}
                {children}
            </div>
        )
    }
)
ToastCard.displayName = 'ToastCard'

// ── Toast placement ───────────────────────────────────────────────────
export type ToastPlacement = 'bottom-right' | 'top-center'

// Older toasts stack away from the screen edge, upward from the bottom and downward from the top.
// `away` is the sign of that direction in the CSS math below.
function stackStyles(away: '-1' | '1', origin: 'top' | 'bottom'): React.CSSProperties {
    return {
        '--gap': '0.75rem',
        '--peek': '0.75rem',
        '--scale': 'calc(max(0, 1 - (var(--toast-index) * 0.1)))',
        '--shrink': 'calc(1 - var(--scale))',
        '--height': 'var(--toast-frontmost-height, var(--toast-height))',
        '--offset-y': `calc(${away} * (var(--toast-offset-y) + (var(--toast-index) * var(--gap))) + var(--toast-swipe-movement-y))`,
        position: 'absolute',
        right: 0,
        [origin]: 0,
        width: '100%',
        // Collapsed cards take the front card's height so a shorter one still peeks out from behind it.
        height: 'var(--height)',
        zIndex: 'calc(1000 - var(--toast-index))',
        transformOrigin: `${origin} center`,
        transform: `translateX(var(--toast-swipe-movement-x)) translateY(calc(var(--toast-swipe-movement-y) + ${away} * ((var(--toast-index) * var(--peek)) + (var(--shrink) * var(--height))))) scale(var(--scale))`,
        transition: 'transform 0.5s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.5s, height 0.15s',
    } as React.CSSProperties
}

const toastPlacements: Record<
    ToastPlacement,
    {
        viewportClassName: string
        cardClassName: string
        rootStyle: React.CSSProperties
        swipeDirection: Toast.Root.Props['swipeDirection']
        gapHitArea: 'above' | 'below'
    }
> = {
    'bottom-right': {
        viewportClassName: 'bottom-4 right-4',
        cardClassName:
            'data-[starting-style]:![transform:translateY(150%)] data-[ending-style]:![transform:translateY(150%)]',
        rootStyle: stackStyles('-1', 'bottom'),
        swipeDirection: ['down', 'right'],
        gapHitArea: 'below',
    },
    'top-center': {
        viewportClassName:
            'top-[calc(1rem+env(safe-area-inset-top))] left-1/2 -translate-x-1/2 max-w-[calc(100vw-2rem)]',
        cardClassName:
            'data-[starting-style]:![transform:translateY(-150%)] data-[ending-style]:![transform:translateY(-150%)]',
        rootStyle: stackStyles('1', 'top'),
        swipeDirection: 'up',
        gapHitArea: 'above',
    },
}

// ── Provider ──────────────────────────────────────────────────────────
type ToastProviderProps = {
    children: React.ReactNode
    limit?: number
    timeout?: number
    /** Where the stack sits; `top-center` suits a phone, where the bottom holds the tab bar. */
    placement?: ToastPlacement
}

function ToastProvider({
    children,
    limit = 3,
    timeout = 5000,
    placement = 'bottom-right',
}: ToastProviderProps): React.ReactElement {
    return (
        <Toast.Provider toastManager={toastManager} limit={limit} timeout={timeout}>
            <Toast.Provider toastManager={anchoredToastManager} limit={limit} timeout={timeout}>
                {children}
                <AnchoredToastViewport />
            </Toast.Provider>
            <ToastViewport placement={placement} />
        </Toast.Provider>
    )
}

// ── Viewport + list ───────────────────────────────────────────────────
function closingAction(
    manager: { close: (toastId: string) => void },
    toastId: string,
    action: ToastAction | undefined
): ToastAction | undefined {
    if (!action) {
        return undefined
    }
    return {
        label: action.label,
        onClick: () => {
            manager.close(toastId)
            action.onClick()
        },
    }
}

function ToastViewport({ placement }: { placement: ToastPlacement }): React.ReactElement {
    const manager = Toast.useToastManager<ToastActionData>()
    const layout = toastPlacements[placement]

    return (
        <Toast.Portal>
            <Toast.Viewport
                data-quill
                data-quill-portal="toast"
                data-slot="toast-viewport"
                data-placement={placement}
                className={cn('fixed w-[360px]', layout.viewportClassName)}
            >
                {manager.toasts.map((t) => {
                    const toastType = t.type as ToastType | undefined

                    return (
                        <Toast.Root
                            key={t.id}
                            toast={t}
                            swipeDirection={layout.swipeDirection}
                            style={layout.rootStyle}
                            render={
                                <ToastCard
                                    toastTitle={t.title}
                                    toastDescription={t.description}
                                    icon={toastType ? toastIconMap[toastType] : undefined}
                                    showGapHitArea={layout.gapHitArea}
                                    action={closingAction(manager, t.id, t.data?.action)}
                                    secondaryAction={closingAction(manager, t.id, t.data?.secondaryAction)}
                                    onDismiss={() => {
                                        manager.close(t.id)
                                        t.data?.onDismiss?.()
                                    }}
                                    className={cn(
                                        'm-0 p-3',
                                        'data-[expanded]:![transform:translateX(var(--toast-swipe-movement-x))_translateY(var(--offset-y))]',
                                        'data-[expanded]:![height:var(--toast-height)]',
                                        'not-data-[expanded]:overflow-hidden',
                                        layout.cardClassName,
                                        'data-[ending-style]:opacity-0',
                                        'data-[limited]:opacity-0'
                                    )}
                                />
                            }
                        />
                    )
                })}
            </Toast.Viewport>
        </Toast.Portal>
    )
}

// ── Anchored viewport ─────────────────────────────────────────────────
function AnchoredToastViewport(): React.ReactElement {
    const manager = Toast.useToastManager<ToastActionData>()

    return (
        <Toast.Portal>
            <Toast.Viewport data-quill data-quill-portal="toast" data-slot="anchored-toast-viewport" className="fixed">
                {manager.toasts.map((t) => {
                    return (
                        // The caller's side and offset win; top and 8px are only the defaults.
                        <Toast.Positioner
                            key={t.id}
                            toast={t}
                            side={t.positionerProps?.side ?? 'top'}
                            sideOffset={t.positionerProps?.sideOffset ?? 8}
                        >
                            <Toast.Root
                                toast={t}
                                render={
                                    <ToastCard
                                        toastTitle={t.title}
                                        toastDescription={t.description}
                                        action={closingAction(manager, t.id, t.data?.action)}
                                        secondaryAction={closingAction(manager, t.id, t.data?.secondaryAction)}
                                        onDismiss={
                                            t.data?.action
                                                ? () => {
                                                      manager.close(t.id)
                                                      t.data?.onDismiss?.()
                                                  }
                                                : undefined
                                        }
                                        className={cn(
                                            // the viewport is a zero-width fixed box, so without this the card
                                            // collapses to its longest word
                                            'w-max max-w-[320px]',
                                            'data-[starting-style]:opacity-0 data-[starting-style]:scale-95',
                                            'data-[ending-style]:opacity-0 data-[ending-style]:scale-95',
                                            'transition-[opacity,transform] duration-200 ease-out'
                                        )}
                                    />
                                }
                            />
                        </Toast.Positioner>
                    )
                })}
            </Toast.Viewport>
        </Toast.Portal>
    )
}

// ── Convenience API ───────────────────────────────────────────────────
function toastData({ action, secondaryAction, onDismiss }: ToastOptions): ToastActionData | undefined {
    return action || secondaryAction || onDismiss ? { action, secondaryAction, onDismiss } : undefined
}

function addToast(options: ToastOptions): string {
    const { title, description, type, timeout, onClose } = options
    return toastManager.add({
        title,
        description,
        type,
        timeout,
        onClose,
        data: toastData(options),
    })
}

function toast(options: ToastOptions): string {
    return addToast(options)
}

toast.success = (options: Omit<ToastOptions, 'type'>): string => {
    return addToast({ ...options, type: 'success' })
}

toast.info = (options: Omit<ToastOptions, 'type'>): string => {
    return addToast({ ...options, type: 'info' })
}

toast.warning = (options: Omit<ToastOptions, 'type'>): string => {
    return addToast({ ...options, type: 'warning' })
}

toast.error = (options: Omit<ToastOptions, 'type'>): string => {
    return addToast({ ...options, type: 'error' })
}

toast.loading = (options: Omit<ToastOptions, 'type'>): string => {
    return addToast({ ...options, type: 'loading', timeout: 0 })
}

/** Closes the toast with this id, or every toast when no id is given. */
toast.dismiss = (id?: string): void => {
    toastManager.close(id)
}

toast.update = (id: string, options: ToastOptions): void => {
    const { title, description, type, timeout, onClose } = options
    toastManager.update(id, {
        title,
        description,
        type,
        timeout,
        onClose,
        data: toastData(options),
    })
}

// ── Anchored toast API ────────────────────────────────────────────────
type AnchoredToastOptions = ToastOptions & {
    anchor: Element | null
    side?: 'top' | 'bottom' | 'left' | 'right'
    sideOffset?: number
    onClose?: () => void
}

function anchoredToast(options: AnchoredToastOptions): string {
    const { title, description, type, timeout, anchor, side, sideOffset, onClose } = options
    return anchoredToastManager.add({
        title,
        description,
        type,
        timeout,
        onClose,
        data: toastData(options),
        positionerProps: {
            anchor,
            side,
            sideOffset,
        },
    })
}

anchoredToast.dismiss = (id: string): void => {
    anchoredToastManager.close(id)
}

export {
    anchoredToast,
    anchoredToastManager,
    toast,
    ToastCard,
    toastIconMap,
    toastManager,
    ToastProvider,
    type AnchoredToastOptions,
    type ToastAction,
    type ToastCardProps,
    type ToastOptions,
    type ToastType,
}
