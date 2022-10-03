import React, { useState } from 'react'
import { LemonButton, LemonButtonProps } from 'lib/components/LemonButton'
import { LemonModal, LemonModalProps } from '../LemonModal'
import ReactDOM from 'react-dom'

export type LemonDialogButtonProps = Pick<LemonButtonProps, 'type' | 'status' | 'icon' | 'onClick'> & {
    children: React.ReactNode
}

export type LemonDialogProps = Pick<LemonModalProps, 'title' | 'description' | 'width' | 'inline'> & {
    primaryButton?: LemonDialogButtonProps
    secondaryButton?: LemonDialogButtonProps
    tertiaryButton?: LemonDialogButtonProps
    onClose?: () => void
    onAfterClose?: () => void
}

export function LemonDialog({
    onAfterClose,
    onClose,
    primaryButton,
    tertiaryButton,
    secondaryButton,
    ...props
}: LemonDialogProps): JSX.Element {
    const [isOpen, setIsOpen] = useState(true)

    primaryButton = primaryButton || {
        children: 'Okay',
    }
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
        />
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
