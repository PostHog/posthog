import { Toast } from '@base-ui/react/toast'
import { CircleCheckIcon, InfoIcon, XIcon, TriangleAlertIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from './button'
import { cn } from './lib/utils'
import { Spinner } from './spinner'

// ── Global manager ────────────────────────────────────────────────────
type ToastActionData = {
    action?: {
        label: string
        onClick: () => void
    }
}

const toastManager = Toast.createToastManager<ToastActionData>()
const anchoredToastManager = Toast.createToastManager<ToastActionData>()

// ── Types ─────────────────────────────────────────────────────────────
type ToastType = 'success' | 'info' | 'warning' | 'error' | 'loading'

type ToastOptions = {
    title?: string
    description?: string
    type?: ToastType
    timeout?: number
    onClose?: () => void
    action?: {
        label: string
        onClick: () => void
    }
}

// ── Icon map ──────────────────────────────────────────────────────────
const toastIconMap: Record<ToastType, React.ReactNode> = {
    success: <CircleCheckIcon className="size-6 bg-success/50 text-success-foreground p-1 rounded-sm" />,
    info: <InfoIcon className="size-6 bg-info/50 text-info-foreground p-1 rounded-sm" />,
    warning: <TriangleAlertIcon className="size-6 bg-warning/50 text-warning-foreground p-1 rounded-sm" />,
    error: <XIcon className="size-6 bg-destructive/50 text-destructive-foreground p-1 rounded-sm" />,
    loading: <Spinner className="size-6 text-foreground/60 p-1 rounded-sm" />,
}

// ── ToastCard ─────────────────────────────────────────────────────────
type ToastCardAction = {
    label: string
    onClick: () => void
}

type ToastCardProps = React.ComponentPropsWithRef<'div'> & {
    toastTitle?: React.ReactNode
    toastDescription?: React.ReactNode
    icon?: React.ReactNode
    action?: ToastCardAction
    onDismiss?: () => void
    showGapHitArea?: boolean
}

const ToastCard = React.forwardRef<HTMLDivElement, ToastCardProps>(
    ({ className, toastTitle, toastDescription, icon, action, onDismiss, showGapHitArea, children, ...props }, ref) => {
        const onlyTitle = toastTitle !== undefined && toastDescription === undefined
        const onlyDescription = toastDescription !== undefined && toastTitle === undefined
        return (
            <div
                ref={ref}
                className={cn(
                    'box-border select-none cursor-default relative',
                    'rounded-sm border border-border bg-popover text-popover-foreground p-2 px-3',
                    'bg-clip-padding',
                    className
                )}
                {...props}
            >
                {showGapHitArea && (
                    <span
                        className="pointer-events-auto absolute left-0 top-full w-full"
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
                        {toastTitle && <div className="text-xs font-medium leading-snug">{toastTitle}</div>}
                        {toastDescription && <div className="text-xs text-muted-foreground">{toastDescription}</div>}
                    </div>
                </div>
                {action && (
                    <div className="flex items-center gap-1.5 mt-2">
                        {icon && <span className="size-6 shrink-0" />}
                        <button
                            type="button"
                            className="rounded-sm border border-border bg-popover px-2 py-1 text-xs font-medium hover:bg-accent transition-colors"
                            onClick={action.onClick}
                        >
                            {action.label}
                        </button>
                    </div>
                )}
                {onDismiss && (
                    <Button
                        size="icon-sm"
                        className={cn(
                            'absolute right-2',
                            (onlyTitle && 'top-1.5') || (onlyDescription && 'top-1.5') || 'top-2'
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

// ── Toast root styles (CSS variable heavy — can't be pure Tailwind) ──
const toastRootStyles: React.CSSProperties = {
    '--gap': '0.75rem',
    '--peek': '0.75rem',
    '--scale': 'calc(max(0, 1 - (var(--toast-index) * 0.1)))',
    '--shrink': 'calc(1 - var(--scale))',
    '--height': 'var(--toast-frontmost-height, var(--toast-height))',
    '--offset-y':
        'calc(var(--toast-offset-y) * -1 + (var(--toast-index) * var(--gap) * -1) + var(--toast-swipe-movement-y))',
    position: 'absolute',
    right: 0,
    bottom: 0,
    left: 'auto',
    width: '100%',
    height: 'auto',
    zIndex: 'calc(1000 - var(--toast-index))',
    transformOrigin: 'bottom center',
    transform:
        'translateX(var(--toast-swipe-movement-x)) translateY(calc(var(--toast-swipe-movement-y) - (var(--toast-index) * var(--peek)) - (var(--shrink) * var(--height)))) scale(var(--scale))',
    transition: 'transform 0.5s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.5s, height 0.15s',
} as React.CSSProperties

// ── Provider ──────────────────────────────────────────────────────────
type ToastProviderProps = {
    children: React.ReactNode
    limit?: number
    timeout?: number
}

function ToastProvider({ children, limit = 3, timeout = 5000 }: ToastProviderProps): React.ReactElement {
    return (
        <Toast.Provider toastManager={toastManager} limit={limit} timeout={timeout}>
            <Toast.Provider toastManager={anchoredToastManager} limit={limit} timeout={timeout}>
                {children}
                <AnchoredToastViewport />
            </Toast.Provider>
            <ToastViewport />
        </Toast.Provider>
    )
}

// ── Viewport + list ───────────────────────────────────────────────────
function ToastViewport(): React.ReactElement {
    const manager = Toast.useToastManager<ToastActionData>()

    return (
        <Toast.Portal>
            <Toast.Viewport data-quill className="fixed bottom-4 right-4 z-[100] w-[360px]">
                {manager.toasts.map((t) => {
                    const toastType = t.type as ToastType | undefined

                    return (
                        <Toast.Root
                            key={t.id}
                            toast={t}
                            style={toastRootStyles}
                            render={
                                <ToastCard
                                    toastTitle={t.title}
                                    toastDescription={t.description}
                                    icon={toastType ? toastIconMap[toastType] : undefined}
                                    showGapHitArea
                                    action={
                                        t.data?.action
                                            ? {
                                                  label: t.data.action.label,
                                                  onClick: () => {
                                                      toastManager.close(t.id)
                                                      t.data?.action?.onClick()
                                                  },
                                              }
                                            : undefined
                                    }
                                    onDismiss={() => toastManager.close(t.id)}
                                    className={cn(
                                        'm-0 p-3',
                                        'data-[expanded]:![transform:translateX(var(--toast-swipe-movement-x))_translateY(var(--offset-y))]',
                                        'data-[expanded]:![height:var(--toast-height)]',
                                        'data-[starting-style]:![transform:translateY(150%)]',
                                        'data-[ending-style]:![transform:translateY(150%)]',
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
            <Toast.Viewport data-quill className="fixed z-[100]">
                {manager.toasts.map((t) => {
                    return (
                        <Toast.Positioner key={t.id} toast={t} side="top" sideOffset={8}>
                            <Toast.Root
                                toast={t}
                                render={
                                    <ToastCard
                                        toastTitle={t.title}
                                        toastDescription={t.description}
                                        className={cn(
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
function addToast(options: ToastOptions): string {
    const { title, description, type, timeout, onClose, action } = options
    return toastManager.add({
        title,
        description,
        type,
        timeout,
        onClose,
        data: action ? { action } : undefined,
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

toast.dismiss = (id: string): void => {
    toastManager.close(id)
}

toast.update = (id: string, options: ToastOptions): void => {
    const { title, description, type, timeout, onClose, action } = options
    toastManager.update(id, {
        title,
        description,
        type,
        timeout,
        onClose,
        data: action ? { action } : undefined,
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
    const { title, description, type, timeout, action, anchor, side, sideOffset, onClose } = options
    return anchoredToastManager.add({
        title,
        description,
        type,
        timeout,
        onClose,
        data: action ? { action } : undefined,
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
    type ToastCardProps,
    type ToastOptions,
    type ToastType,
}
