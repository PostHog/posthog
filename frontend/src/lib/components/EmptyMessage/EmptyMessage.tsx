import './EmptyMessage.scss'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

export interface EmptyMessageProps {
    title: string
    description: string
    buttonText?: string
    buttonTo?: string
    buttonOnClick?: () => void
    buttonDataAttr?: string
    // Sits next to the main button, for a second way out of the empty state.
    secondaryButton?: { text: string; onClick: () => void; dataAttr?: string }
    size?: 'small' | 'medium' | 'large'
}

export function EmptyMessage({
    title,
    description,
    buttonText,
    buttonTo,
    buttonOnClick,
    buttonDataAttr,
    secondaryButton,
    size = 'medium',
}: EmptyMessageProps): JSX.Element {
    return (
        <div className="empty-message">
            <div className="flex flex-col h-full items-center justify-center m-5">
                <h3 className="title">{title}</h3>

                <p className="text-secondary description">{description}</p>
                <div className="flex flex-wrap justify-center gap-2">
                    {buttonText && (
                        <LemonButton
                            type="secondary"
                            to={buttonTo}
                            onClick={buttonOnClick}
                            size={size}
                            data-attr={buttonDataAttr}
                        >
                            {buttonText}
                        </LemonButton>
                    )}
                    {secondaryButton && (
                        <LemonButton
                            type="secondary"
                            onClick={secondaryButton.onClick}
                            size={size}
                            data-attr={secondaryButton.dataAttr}
                        >
                            {secondaryButton.text}
                        </LemonButton>
                    )}
                </div>
            </div>
        </div>
    )
}
