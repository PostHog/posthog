import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { LemonModal, LemonModalProps } from 'lib/lemon-ui/LemonModal'
import { ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import { createRoot, Root } from 'react-dom/client'

import { LemonDialogFormPropsType, lemonDialogLogic } from './lemonDialogLogic'

export type LemonFormDialogProps = LemonDialogFormPropsType &
    Omit<LemonDialogProps, 'primaryButton' | 'secondaryButton' | 'tertiaryButton'> & {
        initialValues: Record<string, any>
        onSubmit: (values: Record<string, any>) => void | Promise<void>
        shouldAwaitSubmit?: boolean
    }

export type LemonDialogProps = Pick<
    LemonModalProps,
    'title' | 'description' | 'width' | 'maxWidth' | 'inline' | 'footer' | 'zIndex'
> & {
    primaryButton?: LemonButtonProps | null
    secondaryButton?: LemonButtonProps | null
    tertiaryButton?: LemonButtonProps | null
    initialFormValues?: Record<string, any>
    content?: ReactNode
    onClose?: () => void
    onAfterClose?: () => void
    closeOnNavigate?: boolean
    shouldAwaitSubmit?: boolean
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
    shouldAwaitSubmit = false,
    footer,
    ...props
}: LemonDialogProps): JSX.Element {
    const [isOpen, setIsOpen] = useState(true)
    const { currentLocation } = useValues(router)
    const lastLocation = useRef(currentLocation.pathname)
    const [isLoading, setIsLoading] = useState(false)

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

    const renderButton = (button: LemonButtonProps | null | undefined): JSX.Element | null => {
        if (!button) {
            return null
        }
        return (
            <LemonButton
                type="secondary"
                {...button}
                loading={button === primaryButton && shouldAwaitSubmit ? isLoading : undefined}
                // eslint-disable-next-line @typescript-eslint/no-misused-promises
                onClick={async (e) => {
                    if (button === primaryButton && shouldAwaitSubmit) {
                        setIsLoading(true)
                        try {
                            // eslint-disable-next-line @typescript-eslint/await-thenable
                            await button.onClick?.(e)
                        } finally {
                            setIsLoading(false)
                        }
                    } else {
                        button.onClick?.(e)
                    }
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
            {content}
        </LemonModal>
    )
}

export const LemonFormDialog = ({
    initialValues = {},
    onSubmit,
    errors,
    ...props
}: LemonFormDialogProps): JSX.Element => {
    const logic = lemonDialogLogic({ errors })
    const { form, isFormValid, formValidationErrors } = useValues(logic)
    const { setFormValues } = useActions(logic)

    const firstError = useMemo(() => Object.values(formValidationErrors)[0] as string, [formValidationErrors])

    const primaryButton: LemonDialogProps['primaryButton'] = {
        type: 'primary',
        children: 'Submit',
        htmlType: 'submit',
        // eslint-disable-next-line @typescript-eslint/no-misused-promises
        onClick: props.shouldAwaitSubmit ? async () => await onSubmit(form) : () => void onSubmit(form),
        disabledReason: !isFormValid ? firstError : undefined,
    }

    const secondaryButton: LemonDialogProps['secondaryButton'] = {
        type: 'secondary',
        children: 'Cancel',
    }

    useEffect(() => {
        setFormValues(initialValues)
    }, [])

    return (
        <Form
            logic={lemonDialogLogic}
            formKey="form"
            onKeyDown={(e: React.KeyboardEvent<HTMLFormElement>): void => {
                if (e.key === 'Enter' && primaryButton?.htmlType === 'submit' && isFormValid) {
                    void onSubmit(form)
                }
            }}
        >
            <LemonDialog {...props} primaryButton={primaryButton} secondaryButton={secondaryButton} />
        </Form>
    )
}

function createAndInsertRoot(): { root: Root; onDestroy: () => void } {
    const div = document.createElement('div')
    const root = createRoot(div)
    function destroy(): void {
        root.unmount()
        if (div.parentNode) {
            div.parentNode.removeChild(div)
        }
    }

    document.body.appendChild(div)
    return { root, onDestroy: destroy }
}

LemonDialog.open = (props: LemonDialogProps) => {
    const { root, onDestroy } = createAndInsertRoot()
    root.render(<LemonDialog {...props} onAfterClose={onDestroy} />)
}

LemonDialog.openForm = (props: LemonFormDialogProps) => {
    const { root, onDestroy } = createAndInsertRoot()
    root.render(<LemonFormDialog {...props} onAfterClose={onDestroy} />)
}
