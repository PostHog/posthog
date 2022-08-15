import React from 'react'
import './EmptyMessage.scss'
import { LemonButton } from '../LemonButton'

export interface EmptyMessageProps {
    title: string
    description: string
    buttonText: string
    buttonTo?: string
    buttonHref?: string
}

export function EmptyMessage({ title, description, buttonText, buttonTo, buttonHref }: EmptyMessageProps): JSX.Element {
    return (
        <div className="empty-message">
            <div className="flex flex-col h-full items-center justify-center m-5">
                <h3 className="title">{title}</h3>

                <p className="text-muted description">{description}</p>
                <LemonButton type="secondary" to={buttonTo} href={buttonHref}>
                    {buttonText}
                </LemonButton>
            </div>
        </div>
    )
}
