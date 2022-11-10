import { useEffect, useRef, useState } from 'react'
import { LemonButton, LemonButtonProps } from 'lib/components/LemonButton'
import { LemonModal, LemonModalProps } from '../LemonModal'
import ReactDOM from 'react-dom'
import { useValues } from 'kea'
import { router } from 'kea-router'

export type LemonDialogButtonProps = Pick<LemonButtonProps, 'type' | 'status' | 'icon' | 'onClick'> & {
    children: React.ReactNode
}

export type LemonDialogProps = Pick<LemonModalProps, 'title' | 'description' | 'width' | 'inline'> & {
    primaryButton?: LemonDialogButtonProps
    secondaryButton?: LemonDialogButtonProps
    tertiaryButton?: LemonDialogButtonProps
    content?: React.ReactNode
    onClose?: () => void
    onAfterClose?: () => void
    closeOnNavigate?: boolean
}

export function LemonDialog({
    onAfterClose,
    onClose,
    primaryButton,
    tertiaryButton,
    secondaryButton,
    content,
    closeOnNavigate = true,
    ...props
}: LemonDialogProps): JSX.Element {
    const [isOpen, setIsOpen] = useState(true)
    const { currentLocation } = useValues(router)
    const lastLocation = useRef(currentLocation.pathname)

    primaryButton = primaryButton || {
        children: 'Okay',
    }

    useEffect(() => {
        if (lastLocation.current !== currentLocation.pathname && closeOnNavigate) {
            setIsOpen(false)
        }
        lastLocation.current = currentLocation.pathname
    }, [currentLocation])

    return (
        <LemonModal
            {...props}
            isOpen={isOpen}
            onClose={() => setIsOpen(false)}
            onAfterClose={() => onAfterClose?.()}
            footer={
                <>
                    <div className="flex-1">
                        {tertiaryButton ? (
                            <LemonButton
                                type="secondary"
                                {...tertiaryButton}
                                onClick={(e) => {
                                    tertiaryButton.onClick?.(e)
                                    setIsOpen(false)
                                }}
                            />
                        ) : null}
                    </div>
                    {secondaryButton ? (
                        <LemonButton
                            type="secondary"
                            {...secondaryButton}
                            onClick={(e) => {
                                secondaryButton.onClick?.(e)
                                setIsOpen(false)
                            }}
                        />
                    ) : null}
                    {primaryButton ? (
                        <LemonButton
                            type="primary"
                            {...primaryButton}
                            onClick={(e) => {
                                primaryButton?.onClick?.(e)
                                setIsOpen(false)
                            }}
                        />
                    ) : null}
                </>
            }
        >
            {content}
        </LemonModal>
    )
}

export type LemonDialogOpenConfig = Omit<LemonDialogProps, 'onClose' | 'onAfterClose'>

LemonDialog.open = (props: LemonDialogProps) => {
    const div = document.createElement('div')
    function destroy(): void {
        const unmountResult = ReactDOM.unmountComponentAtNode(div)
        if (unmountResult && div.parentNode) {
            div.parentNode.removeChild(div)
        }
    }

    document.body.appendChild(div)
    ReactDOM.render(<LemonDialog {...props} onAfterClose={destroy} />, div)
    return
}
