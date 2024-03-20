import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { LemonModal, LemonModalProps } from 'lib/lemon-ui/LemonModal'
import { ReactNode, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'

import { lemonDialogLogic } from './lemonDialogLogic'

type ButtonProps = Omit<LemonButtonProps, 'onClick'> & { onClick?: (event: any, form: any) => void }

export type LemonDialogProps = Pick<
    LemonModalProps,
    'title' | 'description' | 'width' | 'maxWidth' | 'inline' | 'footer'
> & {
    primaryButton?: ButtonProps | null
    secondaryButton?: ButtonProps | null
    tertiaryButton?: ButtonProps | null
    initialFormValues?: Record<string, any>
    content?: ReactNode
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
    initialFormValues,
    closeOnNavigate = true,
    footer,
    ...props
}: LemonDialogProps): JSX.Element {
    const [isOpen, setIsOpen] = useState(true)
    const { currentLocation } = useValues(router)
    const lastLocation = useRef(currentLocation.pathname)
    const logic = lemonDialogLogic()
    const { form } = useValues(logic)
    const { setFormValues, setFormManualErrors } = useActions(logic)

    useEffect(() => {
        if (initialFormValues) {
            setFormValues(initialFormValues)
            setFormManualErrors({ name: true ? 'Please enter your name' : undefined })
        }
    }, [])

    primaryButton =
        primaryButton ||
        (primaryButton === null
            ? null
            : {
                  children: 'Okay',
              })
    if (primaryButton) {
        primaryButton.type = primaryButton.type || 'primary'
    }

    const renderButton = (button: ButtonProps | null | undefined): JSX.Element | null => {
        if (!button) {
            return null
        }
        return (
            <LemonButton
                type="secondary"
                {...button}
                onClick={(e) => {
                    button.onClick?.(e, form)
                    setIsOpen(false)
                }}
            />
        )
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
                footer ? (
                    footer
                ) : primaryButton || secondaryButton || tertiaryButton ? (
                    <>
                        <div className="flex-1">{renderButton(tertiaryButton)}</div>
                        {renderButton(secondaryButton)}
                        {renderButton(primaryButton)}
                    </>
                ) : null
            }
        >
            <Form logic={lemonDialogLogic} formKey="form">
                {content}
            </Form>
        </LemonModal>
    )
}

LemonDialog.open = (props: LemonDialogProps) => {
    const div = document.createElement('div')
    const root = createRoot(div)
    function destroy(): void {
        root.unmount()
        if (div.parentNode) {
            div.parentNode.removeChild(div)
        }
    }

    document.body.appendChild(div)
    root.render(<LemonDialog {...props} onAfterClose={destroy} />)
    return
}
