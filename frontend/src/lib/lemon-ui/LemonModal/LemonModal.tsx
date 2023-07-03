import { useRef, useState } from 'react'
import { CSSTransition } from 'react-transition-group'
import clsx from 'clsx'
import Modal from 'react-modal'

import { IconClose } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import './LemonModal.scss'

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
    inline?: boolean
    title?: React.ReactNode
    description?: React.ReactNode
    footer?: React.ReactNode
    /** When enabled, the modal content will only include children allowing greater customisation */
    simple?: boolean
    closable?: boolean
    /** Wether the modal should close on a secondary action i.e. clicking on the overlay or pressing esc */
    shouldCloseOnSecondaryAction?: boolean
    /** Expands the modal to fill the entire screen */
    fullScreen?: boolean
    /**
     * A modal launched from a popover can appear behind the popover. This allows you to force the modal to appear above the popover.
     * */
    forceAbovePopovers?: boolean
    contentRef?: React.RefCallback<HTMLDivElement>
    overlayRef?: React.RefCallback<HTMLDivElement>
    getPopupContainer?: () => HTMLElement
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
    shouldCloseOnSecondaryAction,
    fullScreen = false,
    forceAbovePopovers = false,
    contentRef,
    overlayRef,
    getPopupContainer,
}: LemonModalProps): JSX.Element {
    const nodeRef = useRef(null)
    const [animateClose, setAnimateClose] = useState(false)

    const modalContent = (
        <CSSTransition
            nodeRef={nodeRef}
            in={animateClose}
            onEntered={() => setAnimateClose(false)}
            timeout={1250}
            classNames="LemonModal__container--animate-close"
        >
            <div ref={nodeRef} className="LemonModal__container">
                {closable && (
                    <div className="LemonModal__closebutton">
                        <LemonButton
                            icon={<IconClose />}
                            size="small"
                            status="stealth"
                            onClick={onClose}
                            aria-label="close"
                        />
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
        </CSSTransition>
    )

    width = !fullScreen ? width : undefined

    return inline ? (
        // eslint-disable-next-line react/forbid-dom-props
        <div className="LemonModal ReactModal__Content--after-open" style={{ width }}>
            {modalContent}
        </div>
    ) : (
        <Modal
            isOpen={isOpen}
            onRequestClose={() => {
                if (shouldCloseOnSecondaryAction) {
                    onClose?.()
                } else {
                    setAnimateClose(true)
                }
            }}
            shouldCloseOnOverlayClick={closable}
            shouldCloseOnEsc={closable}
            onAfterClose={onAfterClose}
            closeTimeoutMS={250}
            className={clsx('LemonModal', fullScreen && 'LemonModal--fullscreen')}
            overlayClassName={clsx(
                'LemonModal__overlay',
                forceAbovePopovers && 'LemonModal__overlay--force-modal-above-popovers'
            )}
            style={{
                content: {
                    width: width,
                },
            }}
            appElement={document.getElementById('root') as HTMLElement}
            contentRef={contentRef}
            overlayRef={overlayRef}
            parentSelector={getPopupContainer}
        >
            {modalContent}
        </Modal>
    )
}

LemonModal.Header = LemonModalHeader
LemonModal.Footer = LemonModalFooter
LemonModal.Content = LemonModalContent
