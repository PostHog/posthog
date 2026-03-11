import './LemonDrawer.scss'

import clsx from 'clsx'
import { useId } from 'react'
import Modal from 'react-modal'

import { IconX } from '@posthog/icons'

import { useFloatingContainer } from 'lib/hooks/useFloatingContainerContext'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { Tooltip } from '../Tooltip'

interface LemonDrawerInnerProps {
    children?: React.ReactNode
    className?: string
}

interface LemonDrawerBaseProps {
    children?: React.ReactNode
    isOpen?: boolean
    onClose?: () => void
    onAfterClose?: () => void
    width?: number | string
    description?: React.ReactNode
    footer?: React.ReactNode
    hideCloseButton?: boolean
    /** Disables the backdrop blur and darkening on the overlay */
    overlayTransparent?: boolean
    forceAbovePopovers?: boolean
    contentRef?: React.RefCallback<HTMLDivElement>
    overlayRef?: React.RefCallback<HTMLDivElement>
    'data-attr'?: string
    className?: string
    overlayClassName?: string
}

/** Standard mode: title provides the accessible name via aria-labelledby */
interface LemonDrawerWithTitle extends LemonDrawerBaseProps {
    title: React.ReactNode
    simple?: false
    'aria-label'?: string
}

/** Simple mode: aria-label is required since there is no built-in title */
interface LemonDrawerSimple extends LemonDrawerBaseProps {
    title?: never
    simple: true
    'aria-label': string
}

export type LemonDrawerProps = LemonDrawerWithTitle | LemonDrawerSimple

const LemonDrawerHeader = ({ children, className }: LemonDrawerInnerProps): JSX.Element => {
    return <header className={clsx('LemonDrawer__header', className)}>{children}</header>
}

const LemonDrawerFooter = ({ children, className }: LemonDrawerInnerProps): JSX.Element => {
    return <footer className={clsx('LemonDrawer__footer', className)}>{children}</footer>
}

const LemonDrawerContent = ({ children, className }: LemonDrawerInnerProps): JSX.Element => {
    return <section className={clsx('LemonDrawer__content', className)}>{children}</section>
}

export function LemonDrawer({
    width,
    children,
    isOpen = true,
    onClose,
    onAfterClose,
    title,
    description,
    footer,
    simple,
    hideCloseButton = false,
    overlayTransparent = false,
    forceAbovePopovers = false,
    contentRef,
    overlayRef,
    'aria-label': ariaLabel,
    'data-attr': dataAttr,
    className,
    overlayClassName,
}: LemonDrawerProps): JSX.Element {
    const floatingContainer = useFloatingContainer()
    const titleId = useId()
    const descriptionId = useId()
    const hasVisibleTitle = !simple && !!title

    const drawerContent = (
        <div className="LemonDrawer__container" data-attr={dataAttr}>
            {!hideCloseButton && (
                <div className="LemonDrawer__close">
                    <Tooltip
                        title={
                            <>
                                Close <KeyboardShortcut escape />
                            </>
                        }
                    >
                        <LemonButton icon={<IconX />} size="small" onClick={onClose} aria-label="Close" />
                    </Tooltip>
                </div>
            )}

            <div className="LemonDrawer__layout">
                {simple ? (
                    children
                ) : (
                    <>
                        {title ? (
                            <LemonDrawerHeader>
                                <h3 id={titleId}>{title}</h3>
                                {description ? (
                                    typeof description === 'string' ? (
                                        <p id={descriptionId}>{description}</p>
                                    ) : (
                                        <div id={descriptionId}>{description}</div>
                                    )
                                ) : null}
                            </LemonDrawerHeader>
                        ) : null}

                        {children ? <LemonDrawerContent>{children}</LemonDrawerContent> : null}
                        {footer ? <LemonDrawerFooter>{footer}</LemonDrawerFooter> : null}
                    </>
                )}
            </div>
        </div>
    )

    return (
        // eslint-disable-next-line react/forbid-elements
        <Modal
            isOpen={isOpen}
            onRequestClose={onClose}
            shouldCloseOnOverlayClick
            shouldCloseOnEsc
            onAfterClose={onAfterClose}
            closeTimeoutMS={250}
            className={clsx('LemonDrawer', className)}
            overlayClassName={clsx(
                'LemonDrawer__overlay',
                overlayTransparent && 'LemonDrawer__overlay--transparent',
                forceAbovePopovers && 'LemonDrawer__overlay--force-above-popovers',
                overlayClassName
            )}
            style={{
                content: {
                    width,
                },
            }}
            contentLabel={!hasVisibleTitle ? ariaLabel : undefined}
            aria={{
                labelledby: hasVisibleTitle ? titleId : undefined,
                describedby: hasVisibleTitle && description ? descriptionId : undefined,
            }}
            appElement={document.getElementById('root') as HTMLElement}
            contentRef={contentRef}
            overlayRef={overlayRef}
            parentSelector={floatingContainer ? () => floatingContainer : undefined}
        >
            {drawerContent}
        </Modal>
    )
}

LemonDrawer.Header = LemonDrawerHeader
LemonDrawer.Footer = LemonDrawerFooter
LemonDrawer.Content = LemonDrawerContent
