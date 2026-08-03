import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { ReactNode, forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import { Root, createRoot } from 'react-dom/client'

import { ApiError } from 'lib/api-error'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { LemonModal, LemonModalProps } from 'lib/lemon-ui/LemonModal'
import { uuid } from 'lib/utils/dom'
import { objectsEqual } from 'lib/utils/objects'

import { LemonDialogFormPropsType, lemonDialogLogic } from './lemonDialogLogic'

// A rejected await-submit keeps the dialog open so the user can retry. Capture only genuinely
// unexpected failures — not 4xx validation errors the user is expected to cause (e.g. a reserved
// name), which would otherwise flood the exception tracker on every validation failure.
function captureUnexpectedSubmitError(error: unknown): void {
    if (!(error instanceof ApiError) || (error.status ?? 500) >= 500) {
        posthog.captureException(error)
    }
}

export type LemonFormDialogProps = LemonDialogFormPropsType &
    Omit<LemonDialogProps, 'primaryButton' | 'secondaryButton' | 'content'> & {
        initialValues: Record<string, any>
        onSubmit: (values: Record<string, any>) => void | Promise<void>
        shouldAwaitSubmit?: boolean
        content?: ((isLoading: boolean) => ReactNode) | ReactNode
        /** Override props on the auto-generated submit button (e.g. status, children) */
        primaryButtonProps?: Partial<Pick<LemonButtonProps, 'children' | 'status' | 'type' | 'icon'>>
        /**
         * Once the user has touched the form, ignore overlay clicks so a stray one can't discard
         * what they typed. Escape and the close button still dismiss.
         */
        warnOnUnsavedInput?: boolean
    }

export type LemonDialogProps = Pick<
    LemonModalProps,
    'title' | 'description' | 'width' | 'maxWidth' | 'inline' | 'footer' | 'zIndex' | 'className' | 'hasUnsavedInput'
> & {
    primaryButton?: LemonButtonProps | null
    secondaryButton?: LemonButtonProps | null
    tertiaryButton?: LemonButtonProps | null
    initialFormValues?: Record<string, any>
    content?: ((closeDialog: () => void) => ReactNode) | ReactNode
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
                        } catch (error) {
                            // The submit handler is responsible for surfacing the error to the user
                            // (e.g. via a toast). Keep the dialog open so they can correct and retry,
                            // and capture genuine bugs so they aren't silently swallowed.
                            captureUnexpectedSubmitError(error)
                            return
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

    const handleClose = (): void => {
        setIsOpen(false)
    }

    // Resolve content, supporting both function and static content
    const resolvedContent = typeof content === 'function' ? content(handleClose) : content

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
            {resolvedContent}
        </LemonModal>
    )
})

export const LemonFormDialog = ({
    initialValues = {},
    onSubmit,
    errors,
    content,
    primaryButtonProps,
    dialogKey,
    showErrorsOnTouch,
    warnOnUnsavedInput,
    ...props
}: LemonFormDialogProps): JSX.Element => {
    const logicProps = { errors, dialogKey, showErrorsOnTouch }
    const logic = lemonDialogLogic(logicProps)
    const { form, isFormValid, formValidationErrors } = useValues(logic)
    const { setFormValues, touchFormField } = useActions(logic)
    const [isLoading, setIsLoading] = useState(false)
    const ref = useRef<LemonDialogRef>(null)

    const firstError = useMemo(
        () => Object.values(formValidationErrors).find((error) => Boolean(error)) as string,
        [formValidationErrors]
    )

    // Dirtiness is measured against `initialValues` rather than kea-forms' `formChanged`, which the
    // mount-time `setFormValues` below already flips, or `formTouched`, which only lands on blur.
    const isDirty = useMemo(
        () => Object.keys(form).length > 0 && !objectsEqual(form, initialValues),
        [form, initialValues]
    )

    // Touching every field with an error is what makes those errors visible inline. Needed because
    // an untouched required field has nothing to reveal on its own, so the user would otherwise get
    // no feedback at all from pressing submit.
    const revealValidationErrors = (): void => {
        for (const [name, error] of Object.entries(formValidationErrors)) {
            if (error) {
                touchFormField(name)
            }
        }
    }

    const submit = async (): Promise<boolean> => {
        // A `disabledReason` renders an `aria-disabled` button that still looks and presses like a
        // live one, so clicking it reads as the app ignoring you. Dialogs that show errors inline
        // keep a live button and surface the blocker there instead; the rest have nowhere else to
        // put it, so they stay disabled and never reach this branch.
        if (!isFormValid) {
            revealValidationErrors()
            return false
        }
        if (props.shouldAwaitSubmit) {
            await onSubmit(form)
        } else {
            void onSubmit(form)
        }
        return true
    }

    const primaryButton: LemonDialogProps['primaryButton'] = {
        type: 'primary',
        children: 'Submit',
        ...primaryButtonProps,
        htmlType: 'submit',
        // eslint-disable-next-line @typescript-eslint/no-misused-promises
        onClick: props.shouldAwaitSubmit
            ? async (): Promise<void> => {
                  await submit()
              }
            : () => void submit(),
        disabledReason: isFormValid || showErrorsOnTouch ? undefined : firstError,
        // An invalid submit only reveals the errors, so the dialog has to stay open for the fix.
        preventClosing: !isFormValid,
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

    const onEnter = async (e: React.KeyboardEvent<HTMLFormElement>): Promise<void> => {
        if (e.key !== 'Enter' || primaryButton?.htmlType !== 'submit') {
            return
        }
        let submitted: boolean
        try {
            submitted = await submit()
        } catch (error) {
            // Mirror the button path: keep the dialog open on failure so the user can correct and
            // retry, and capture instead of leaking an unhandled rejection.
            captureUnexpectedSubmitError(error)
            return
        }
        if (submitted) {
            ref?.current?.closeDialog()
        }
    }

    return (
        <Form
            logic={lemonDialogLogic}
            props={logicProps}
            formKey="form"
            onKeyDown={(e: React.KeyboardEvent<HTMLFormElement>): void => void onEnter(e)}
        >
            <LemonDialog
                ref={ref}
                {...props}
                hasUnsavedInput={warnOnUnsavedInput ? isDirty : props.hasUnsavedInput}
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
    // Each dialog gets a unique key so nested dialogs don't share the same
    // lemonDialogLogic instance and corrupt each other's form state.
    root.render(<LemonFormDialog {...props} dialogKey={uuid()} onAfterClose={onDestroy} />)
}
