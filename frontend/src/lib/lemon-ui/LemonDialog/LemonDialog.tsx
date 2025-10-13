import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { ReactNode, forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import { Root, createRoot } from 'react-dom/client'

import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { LemonModal, LemonModalProps } from 'lib/lemon-ui/LemonModal'

import { LemonDialogFormPropsType, lemonDialogLogic } from './lemonDialogLogic'

export type LemonFormDialogProps = LemonDialogFormPropsType &
    Omit<LemonDialogProps, 'primaryButton' | 'secondaryButton'> & {
        initialValues: Record<string, any>
        onSubmit: (values: Record<string, any>) => void | Promise<void>
        shouldAwaitSubmit?: boolean
        content?: ((isLoading: boolean) => ReactNode) | ReactNode
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
    isLoadingCallback?: (isLoading: boolean) => void
}

type LemonDialogRef = {
    closeDialog: () => void
}

type LemonDialogMethods = {
    open: (props: LemonDialogProps) => void
    openForm: (props: LemonFormDialogProps) => void
}

const LemonDialogComponent = forwardRef<LemonDialogRef, LemonDialogProps>(function LemonDialog(
    {
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
        isLoadingCallback,
        ...props
    }: LemonDialogProps,
    ref
): JSX.Element {
    const { currentLocation } = useValues(router)
    const lastLocation = useRef(currentLocation.pathname)
    const [isOpen, setIsOpen] = useState(true)
    const [isLoading, setIsLoading] = useState(false)

    useImperativeHandle(
        ref,
        () => ({
            closeDialog: () => {
                setIsOpen(false)
            },
        }),
        []
    )

    primaryButton =
        primaryButton ||
        (primaryButton === null
            ? null
            : {
                  children: 'Okay',
                  disabledReason: shouldAwaitSubmit && isLoading ? 'Please wait...' : undefined,
              })
    if (primaryButton) {
        primaryButton.type = primaryButton.type || 'primary'
    }

    const renderButton = (button: LemonButtonProps | null | undefined): JSX.Element | null => {
        if (!button) {
            return null
        }

        const { preventClosing, ...buttonProps } = button

        return (
            <LemonButton
                type="secondary"
                {...buttonProps}
                loading={button === primaryButton && shouldAwaitSubmit ? isLoading : undefined}
                // eslint-disable-next-line @typescript-eslint/no-misused-promises
                onClick={async (e) => {
                    if (button === primaryButton && shouldAwaitSubmit) {
                        setIsLoading(true)
                        isLoadingCallback?.(true)
                        try {
                            // eslint-disable-next-line @typescript-eslint/await-thenable
                            await button.onClick?.(e)
                        } finally {
                            setIsLoading(false)
                            isLoadingCallback?.(false)
                        }
                    } else {
                        button.onClick?.(e)
                    }

                    if (!preventClosing) {
                        setIsOpen(false)
                    }
                }}
            />
        )
    }

    useEffect(() => {
        if (lastLocation.current !== currentLocation.pathname && closeOnNavigate) {
            setIsOpen(false)
        }
        lastLocation.current = currentLocation.pathname
    }, [currentLocation]) // oxlint-disable-line react-hooks/exhaustive-deps

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
})

export const LemonFormDialog = ({
    initialValues = {},
    onSubmit,
    errors,
    content,
    ...props
}: LemonFormDialogProps): JSX.Element => {
    const logic = lemonDialogLogic({ errors })
    const { form, isFormValid, formValidationErrors } = useValues(logic)
    const { setFormValues } = useActions(logic)
    const [isLoading, setIsLoading] = useState(false)

    const firstError = useMemo(
        () => Object.values(formValidationErrors).find((error) => Boolean(error)) as string,
        [formValidationErrors]
    )

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

    // Resolve content, supporting both function and static content
    const resolvedContent = typeof content === 'function' ? content(isLoading) : content

    useEffect(() => {
        setFormValues(initialValues)
    }, [setFormValues, initialValues])

    const ref = useRef<LemonDialogRef>(null)

    return (
        <Form
            logic={lemonDialogLogic}
            formKey="form"
            onKeyDown={
                props.shouldAwaitSubmit
                    ? async (e: React.KeyboardEvent<HTMLFormElement>): Promise<void> => {
                          if (e.key === 'Enter' && primaryButton?.htmlType === 'submit' && isFormValid) {
                              await onSubmit(form)
                              ref?.current?.closeDialog()
                          }
                      }
                    : (e: React.KeyboardEvent<HTMLFormElement>): void => {
                          if (e.key === 'Enter' && primaryButton?.htmlType === 'submit' && isFormValid) {
                              void onSubmit(form)
                              ref?.current?.closeDialog()
                          }
                      }
            }
        >
            <LemonDialog
                ref={ref}
                {...props}
                content={resolvedContent}
                primaryButton={primaryButton}
                secondaryButton={secondaryButton}
                isLoadingCallback={setIsLoading}
            />
        </Form>
    )
}

function createAndInsertRoot(): { root: Root; onDestroy: () => void } {
    const div = document.createElement('div')
    const root = createRoot(div)
    function destroy(): void {
        // defer the unmounting to avoid collisions with the rendering cycle
        setTimeout(() => {
            root.unmount()
            if (div.parentNode) {
                div.parentNode.removeChild(div)
            }
        }, 0)
    }

    document.body.appendChild(div)
    return { root, onDestroy: destroy }
}

export const LemonDialog = LemonDialogComponent as typeof LemonDialogComponent & LemonDialogMethods

LemonDialog.open = (props: LemonDialogProps) => {
    const { root, onDestroy } = createAndInsertRoot()
    root.render(<LemonDialog {...props} onAfterClose={onDestroy} />)
}

LemonDialog.openForm = (props: LemonFormDialogProps) => {
    const { root, onDestroy } = createAndInsertRoot()
    root.render(<LemonFormDialog {...props} onAfterClose={onDestroy} />)
}
