import './LemonModal.scss'

import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'
import Modal from 'react-modal'

import { IconX } from '@posthog/icons'

import { useFloatingContainer } from 'lib/hooks/useFloatingContainerContext'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { Tooltip } from '../Tooltip'

interface LemonModalInnerProps {
    children?: React.ReactNode
    className?: string
}

export interface LemonModalContentProps extends LemonModalInnerProps {
    embedded?: boolean
}

export interface LemonModalProps {
    children?: React.ReactNode
    isOpen?: boolean
    onClose?: () => void
    onAfterClose?: () => void
    width?: number | string
    maxWidth?: number | string
    inline?: boolean
    title?: React.ReactNode
    description?: React.ReactNode
    footer?: React.ReactNode
    /** When enabled, the modal content will only include children allowing greater customisation */
    simple?: boolean
    closable?: boolean
    hideCloseButton?: boolean
    /** If there is unsaved input that's not persisted, the modal can't be closed closed on overlay click. */
    hasUnsavedInput?: boolean
    /** Expands the modal to fill the entire screen */
    fullScreen?: boolean
    /**
     * A modal launched from a popover can appear behind the popover. This allows you to force the modal to appear above the popover.
     * */
    forceAbovePopovers?: boolean
    contentRef?: React.RefCallback<HTMLDivElement>
    overlayRef?: React.RefCallback<HTMLDivElement>
    'data-attr'?: string
    /**
     * some components need more fine control of the z-index
     * they can push a specific value to control their position in the stacking order
     */
    zIndex?: '1161' | '1162' | '1166' | '1167' | '1168' | '1169'
    className?: string
    overlayClassName?: string
}

export const LemonModalHeader = ({ children, className }: LemonModalInnerProps): JSX.Element => {
    return <header className={clsx('LemonModal__header', className)}>{children}</header>
}

export const LemonModalFooter = ({ children, className }: LemonModalInnerProps): JSX.Element => {
    return <footer className={clsx('LemonModal__footer', className)}>{children}</footer>
}

export const LemonModalContent = ({ children, className, embedded = false }: LemonModalContentProps): JSX.Element => {
    return (
        <section className={clsx('LemonModal__content', embedded && 'LemonModal__content--embedded', className)}>
            {children}
        </section>
    )
}

export function LemonModal({
    width,
    maxWidth,
    children,
    isOpen = true,
    onClose,
    onAfterClose,
    title,
    description,
    footer,
    inline,
    simple,
    closable = true,
    hasUnsavedInput,
    fullScreen = false,
    forceAbovePopovers = false,
    contentRef,
    overlayRef,
    hideCloseButton = false,
    'data-attr': dataAttr,
    zIndex,
    className,
    overlayClassName,
}: LemonModalProps): JSX.Element {
    const nodeRef = useRef(null)
    const [ignoredOverlayClickCount, setIgnoredOverlayClickCount] = useState(0)

    useEffect(() => setIgnoredOverlayClickCount(0), [hasUnsavedInput]) // Reset when there no longer is unsaved input

    const modalContent = (
        <div ref={nodeRef} className="LemonModal__container" data-attr={dataAttr}>
            {closable && !hideCloseButton && (
                // The key causes the div to be re-rendered, which restarts the animation,
                // providing immediate visual feedback on click
                <div
                    key={ignoredOverlayClickCount}
                    className={clsx(
                        'LemonModal__close',
                        ignoredOverlayClickCount > 0 && 'LemonModal__close--highlighted'
                    )}
                >
                    <Tooltip
                        visible={!!ignoredOverlayClickCount || undefined}
                        title={
                            ignoredOverlayClickCount ? (
                                <>
                                    You have unsaved input that will be discarded.
                                    <br />
                                    Use the <IconX /> button to close explicitly.
                                </>
                            ) : (
                                <>
                                    Close <KeyboardShortcut escape />
                                </>
                            )
                        }
                    >
                        <LemonButton
                            icon={<IconX />}
                            size="small"
                            onClick={onClose}
                            aria-label="close"
                            onMouseEnter={() => setIgnoredOverlayClickCount(0)}
                        />
                    </Tooltip>
                </div>
            )}

            <div className="LemonModal__layout">
                {simple ? (
                    children
                ) : (
                    <>
                        {title ? (
                            <LemonModalHeader>
                                <h3>{title}</h3>
                                {description ? (
                                    typeof description === 'string' ? (
                                        <p>{description}</p>
                                    ) : (
                                        description
                                    )
                                ) : null}
                            </LemonModalHeader>
                        ) : null}

                        {children ? <LemonModalContent>{children}</LemonModalContent> : null}
                        {footer ? <LemonModalFooter>{footer}</LemonModalFooter> : null}
                    </>
                )}
            </div>
        </div>
    )

    width = !fullScreen ? width : undefined
    maxWidth = !fullScreen ? maxWidth : undefined
    const floatingContainer = useFloatingContainer()

    return inline ? (
        // eslint-disable-next-line react/forbid-dom-props
        <div className="LemonModal ReactModal__Content--after-open" style={{ width, maxWidth }}>
            {modalContent}
        </div>
    ) : (
        // eslint-disable-next-line react/forbid-elements
        <Modal
            isOpen={isOpen}
            onRequestClose={(e) => {
                if (hasUnsavedInput && e.type === 'click') {
                    // Only ignore clicks, not Esc
                    setIgnoredOverlayClickCount(ignoredOverlayClickCount + 1)
                } else {
                    onClose?.()
                }
            }}
            shouldCloseOnOverlayClick={closable}
            shouldCloseOnEsc={closable}
            onAfterClose={onAfterClose}
            closeTimeoutMS={250}
            className={clsx('LemonModal', fullScreen && 'LemonModal--fullscreen', className)}
            overlayClassName={clsx(
                'LemonModal__overlay',
                zIndex && `LemonModal__overlay--z-${zIndex}`,
                forceAbovePopovers && 'LemonModal__overlay--force-modal-above-popovers',
                overlayClassName
            )}
            style={{
                content: {
                    width: width,
                    maxWidth,
                },
            }}
            appElement={document.getElementById('root') as HTMLElement}
            contentRef={contentRef}
            overlayRef={overlayRef}
            parentSelector={floatingContainer ? () => floatingContainer : undefined}
        >
            {modalContent}
        </Modal>
    )
}

LemonModal.Header = LemonModalHeader
LemonModal.Footer = LemonModalFooter
LemonModal.Content = LemonModalContent
