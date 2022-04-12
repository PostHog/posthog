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
            <div
                style={{
                    display: 'flex',
                    flexDirection: 'column',
                    height: '100%',
                    justifyContent: 'center',
                    alignItems: 'center',
                    margin: 20,
                }}
            >
                <h3 className="title">{title}</h3>

                <p className="text-muted description">{description}</p>
                <LemonButton type="secondary" style={{ margin: '0 8px' }} to={buttonTo} href={buttonHref}>
                    {buttonText}
                </LemonButton>
            </div>
        </div>
    )
}
