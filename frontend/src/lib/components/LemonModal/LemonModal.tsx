import React from 'react'
import { IconClose } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import Modal from 'react-modal'
import './LemonModal.scss'
import clsx from 'clsx'

export type LemonModalContentProps = {
    children?: React.ReactNode
    className?: string
}

export type LemonModalFooterProps = {
    children?: React.ReactNode
}

interface LemonModalPropsBase {
    children?: React.ReactNode
    onClose?: () => void
    width?: number | string
    title: string | JSX.Element
    description?: string | JSX.Element
    footer?: React.ReactNode
    /** When enabled, the modal content will only include children allowing greater customisation */
    simple?: boolean
    closable?: boolean
    className?: string
}

interface LemonModalPropsInline extends LemonModalPropsBase {
    inline: boolean
    isOpen?: never
    onAfterClose?: never
}

interface LemonModalPropsProper extends LemonModalPropsBase {
    inline?: never
    isOpen: boolean
    onAfterClose?: () => void
}

export type LemonModalProps = LemonModalPropsInline | LemonModalPropsProper

export const LemonModalHeader = ({ children, className }: LemonModalContentProps): JSX.Element => {
    return <header className={clsx('LemonModal__header', className)}>{children}</header>
}

export const LemonModalFooter = ({ children, className }: LemonModalContentProps): JSX.Element => {
    return <footer className={clsx('LemonModal__footer', className)}>{children}</footer>
}

export const LemonModalContent = ({ children, className }: LemonModalContentProps): JSX.Element => {
    return <section className={clsx('LemonModal__content', className)}>{children}</section>
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
    className,
    closable = true,
}: LemonModalProps): JSX.Element {
    const modalContent = (
        <>
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
                                {description ? <p>{description}</p> : null}
                            </LemonModalHeader>
                        ) : null}

                        {children ? <LemonModalContent>{children}</LemonModalContent> : null}
                        {footer ? <LemonModalFooter>{footer}</LemonModalFooter> : null}
                    </>
                )}
            </div>
        </>
    )
    return inline ? (
        <div className={clsx('LemonModal ReactModal__Content--after-open', className)}>{modalContent}</div>
    ) : (
        <Modal
            isOpen={isOpen}
            onRequestClose={onClose}
            shouldCloseOnOverlayClick={closable}
            shouldCloseOnEsc={closable}
            onAfterClose={onAfterClose}
            closeTimeoutMS={250}
            className={clsx('LemonModal', className)}
            overlayClassName="LemonModal__overlay"
            style={{
                content: {
                    width: width,
                },
            }}
            appElement={document.getElementById('root') as HTMLElement}
        >
            {modalContent}
        </Modal>
    )
}

LemonModal.Header = LemonModalHeader
LemonModal.Footer = LemonModalFooter
LemonModal.Content = LemonModalContent
