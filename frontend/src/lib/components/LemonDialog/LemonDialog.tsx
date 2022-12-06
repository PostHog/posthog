import { ReactNode, useEffect, useRef, useState } from 'react'
import { LemonButton, LemonButtonProps } from 'lib/components/LemonButton'
import { LemonModal, LemonModalProps } from '../LemonModal'
import ReactDOM from 'react-dom'
import { useValues } from 'kea'
import { router } from 'kea-router'

export type LemonDialogButtonProps =
    | (Pick<LemonButtonProps, 'type' | 'status' | 'icon' | 'onClick'> & {
          content: ReactNode | ((close: () => void) => ReactNode) // If defined, content overrides default Lemon Button creation
      })
    | (Pick<LemonButtonProps, 'type' | 'status' | 'icon' | 'onClick'> & {
          children: ReactNode
          keepOpen?: boolean
      })

export type LemonDialogProps = Pick<LemonModalProps, 'title' | 'description' | 'width' | 'inline'> & {
    primaryButton?: LemonDialogButtonProps
    secondaryButton?: LemonDialogButtonProps
    tertiaryButton?: LemonDialogButtonProps
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
    closeOnNavigate = true,
    ...props
}: LemonDialogProps): JSX.Element {
    const [isOpen, setIsOpen] = useState(true)
    const { currentLocation } = useValues(router)
    const lastLocation = useRef(currentLocation.pathname)

    primaryButton = primaryButton || {
        children: 'Okay',
    }
    primaryButton.type = primaryButton.type || 'primary'

    const renderButton = (button: LemonDialogButtonProps | undefined): JSX.Element | null => {
        if (!button) {
            return null
        }
        if ('content' in button) {
            return typeof button?.content === 'function'
                ? button?.content(() => {
                      setIsOpen(false)
                  })
                : button?.content
        }
        return (
            <LemonButton
                type="secondary"
                {...button}
                onClick={(e) => {
                    button.onClick?.(e)
                    !button?.keepOpen && setIsOpen(false)
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
                <>
                    <div className="flex-1">{renderButton(tertiaryButton)}</div>
                    {renderButton(secondaryButton)}
                    {renderButton(primaryButton)}
                </>
            }
        >
            {content}
        </LemonModal>
    )
}

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
