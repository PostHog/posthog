import React from 'react'
import { IconClose } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import Modal from 'react-modal'
import './LemonModal.scss'

export type LemonModalHeaderProps = {
    children?: React.ReactNode
}

export type LemonModalFooterProps = {
    children?: React.ReactNode
}

export interface LemonModalProps {
    children?: React.ReactNode
    isOpen: boolean
    onClose: () => void
    width?: number
    inline?: boolean
    title: string | JSX.Element
    description?: string | JSX.Element
    footer?: React.ReactNode
    /** When enabled, the modal content will only include children allowing greater customisation */
    simple?: boolean
}

export const LemonModalHeader = ({ children }: LemonModalHeaderProps): JSX.Element => {
    return <header className="LemonModal__header">{children}</header>
}

export const LemonModalFooter = ({ children }: LemonModalFooterProps): JSX.Element => {
    return <footer className="LemonModal__footer">{children}</footer>
}

export const LemonModalContent = ({ children }: LemonModalFooterProps): JSX.Element => {
    return <section className="LemonModal__content">{children}</section>
}

/** A lightweight wrapper over Ant's Modal for matching Lemon style. */
export function LemonModal({
    width,
    children,
    isOpen,
    onClose,
    title,
    description,
    footer,
    inline,
    simple,
}: LemonModalProps): JSX.Element {
    const modalContent = (
        <>
            <div className="LemonModal__closebutton">
                <LemonButton icon={<IconClose />} status="stealth" onClick={onClose} />
            </div>

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

                        <LemonModalContent>{children}</LemonModalContent>

                        {footer ? <LemonModalFooter>{footer}</LemonModalFooter> : null}
                    </>
                )}
            </div>
        </>
    )
    return inline ? (
        <div className="LemonModal ReactModal__Content--after-open">{modalContent}</div>
    ) : (
        <Modal
            isOpen={isOpen}
            onRequestClose={onClose}
            closeTimeoutMS={250}
            className="LemonModal"
            overlayClassName="LemonModal__overlay"
            style={{
                content: {
                    width: width,
                },
            }}
        >
            {modalContent}
        </Modal>
    )
}

LemonModal.Header = LemonModalHeader
LemonModal.Footer = LemonModalFooter
LemonModal.Content = LemonModalContent
