import './EmptyMessage.scss'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

export interface EmptyMessageProps {
    title: string
    description: string
    buttonText?: string
    buttonTo?: string
    buttonOnClick?: () => void
}

export function EmptyMessage({
    title,
    description,
    buttonText,
    buttonTo,
    buttonOnClick,
}: EmptyMessageProps): JSX.Element {
    return (
        <div className="empty-message">
            <div className="flex flex-col h-full items-center justify-center m-5">
                <h3 className="title">{title}</h3>

                <p className="text-secondary description">{description}</p>
                {buttonText && (
                    <LemonButton type="secondary" to={buttonTo} onClick={buttonOnClick}>
                        {buttonText}
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
