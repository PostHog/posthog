import { IconClose } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import Modal from 'react-modal'
import './LemonModal.scss'
import clsx from 'clsx'

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
    title: React.ReactNode
    description?: React.ReactNode
    footer?: React.ReactNode
    /** When enabled, the modal content will only include children allowing greater customisation */
    simple?: boolean
    closable?: boolean
    /** Expands the modal to fill the entire screen */
    fullScreen?: boolean
    /**
     * This can be used when the modal should be high enough in the z-index stack to be shown above everything
     * except a few parts of the page chrome. See vars.scss for the z-index values
     * */
    bringToFront?: boolean
    contentRef?: React.RefCallback<HTMLDivElement>
    overlayRef?: React.RefCallback<HTMLDivElement>
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
    fullScreen = false,
    bringToFront = false,
    contentRef,
    overlayRef,
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
        </>
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
            onRequestClose={onClose}
            shouldCloseOnOverlayClick={closable}
            shouldCloseOnEsc={closable}
            onAfterClose={onAfterClose}
            closeTimeoutMS={250}
            className={clsx('LemonModal', fullScreen && 'LemonModal--fullscreen')}
            overlayClassName={clsx('LemonModal__overlay', bringToFront && 'LemonModal__overlay--bring-to-front')}
            style={{
                content: {
                    width: width,
                },
            }}
            appElement={document.getElementById('root') as HTMLElement}
            contentRef={contentRef}
            overlayRef={overlayRef}
        >
            {modalContent}
        </Modal>
    )
}

LemonModal.Header = LemonModalHeader
LemonModal.Footer = LemonModalFooter
LemonModal.Content = LemonModalContent
