import './DetailPanel.scss'

import { CSSProperties, ReactNode, RefObject, useEffect } from 'react'

import { cn } from 'lib/utils/css-classes'

export interface DetailPanelRect {
    top: number
    right: number
    height: number
    width: number
}

export interface DetailPanelProps {
    toolbar: ReactNode
    children: ReactNode
    rect: DetailPanelRect
    width: number
    resizer: ReactNode
    containerRef: RefObject<HTMLElement>
    'aria-label': string
    'data-attr': string
}

const FULL_WIDTH_BELOW_SCENE_WIDTH = 900
const TOOLBAR_HEIGHT_REM = 3

export function isDetailPanelFullWidth(sceneWidth: number): boolean {
    return sceneWidth < FULL_WIDTH_BELOW_SCENE_WIDTH
}

export function DetailPanel({
    toolbar,
    children,
    rect,
    width,
    resizer,
    containerRef,
    'aria-label': ariaLabel,
    'data-attr': dataAttr,
}: DetailPanelProps): JSX.Element {
    useEffect(() => {
        const previouslyFocused = document.activeElement
        containerRef.current?.focus({ preventScroll: true })
        return () => {
            if (previouslyFocused instanceof HTMLElement && previouslyFocused.isConnected) {
                previouslyFocused.focus({ preventScroll: true })
            }
        }
    }, [containerRef])

    // The panel is fixed, so a container query cannot see the scene width.
    const isFullWidth = isDetailPanelFullWidth(rect.width)

    return (
        <aside
            ref={containerRef}
            tabIndex={-1}
            aria-label={ariaLabel}
            data-attr={dataAttr}
            className={cn(
                'DetailPanel fixed top-[var(--detail-panel-top)] right-[var(--detail-panel-right)] h-[var(--detail-panel-height)] z-[var(--z-drawer)]',
                'flex flex-col bg-surface-primary border-l border-primary shadow-xl outline-none'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    '--detail-panel-top': `${rect.top}px`,
                    '--detail-panel-right': `calc(100vw - ${rect.right}px)`,
                    '--detail-panel-height': `${rect.height}px`,
                    '--detail-panel-toolbar-height': `${TOOLBAR_HEIGHT_REM}rem`,
                    width: isFullWidth ? rect.width : width,
                    maxWidth: rect.width,
                } as CSSProperties
            }
        >
            {resizer}
            <div className="flex h-[var(--detail-panel-toolbar-height)] shrink-0 items-center gap-2 border-b border-primary px-3">
                {toolbar}
            </div>
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-4">{children}</div>
        </aside>
    )
}
