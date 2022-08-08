import React from 'react'
import { IconClose } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import Modal from 'react-modal'
import './LemonModalV2.scss'

export type LemonModalHeaderProps = {
    children?: React.ReactNode
}

export type LemonModalFooterProps = {
    children?: React.ReactNode
}

export interface LemonModalV2Props {
    children?: React.ReactNode
    isOpen: boolean
    onClose: () => void
    width?: number
    inline?: boolean
    title: string | JSX.Element
    description?: string | JSX.Element
    footer?: React.ReactNode
}

export const LemonModalHeader = ({ children }: LemonModalHeaderProps): JSX.Element => {
    return <div className="LemonModalHeader">{children}</div>
}

export const LemonModalFooter = ({ children }: LemonModalFooterProps): JSX.Element => {
    return <div className="LemonModalFooter">{children}</div>
}

/** A lightweight wrapper over Ant's Modal for matching Lemon style. */
export function LemonModalV2({
    width,
    children,
    isOpen,
    onClose,
    title,
    description,
    footer,
    inline,
}: LemonModalV2Props): JSX.Element {
    const modalContent = (
        <>
            <div className="LemonModal__closebutton">
                <LemonButton icon={<IconClose />} status="stealth" onClick={onClose} />
            </div>

            {title ? (
                <header className="LemonModal__header">
                    <h3>{title}</h3>
                    {description ? <p>{description}</p> : null}
                </header>
            ) : null}

            <div className="LemonModal__content">{children}</div>

            {footer ? <footer className="LemonModal__footer">{footer}</footer> : null}
        </>
    )
    return inline ? (
        <div className="LemonModalV2 ReactModal__Content--after-open">{modalContent}</div>
    ) : (
        <Modal
            isOpen={isOpen}
            onRequestClose={onClose}
            closeTimeoutMS={250}
            className="LemonModalV2"
            overlayClassName="LemonModalV2__overlay"
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

LemonModalV2.Header = LemonModalHeader
LemonModalV2.Footer = LemonModalFooter
