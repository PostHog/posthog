import React from 'react'
import './WelcomeHedgehog.scss'
import hedgehogMain from 'public/hedgehog-bridge-page.png'
import clsx from 'clsx'

interface WelcomeHedgehogProps {
    showWelcomeMessage?: boolean
}

export function WelcomeHedgehog({ showWelcomeMessage = false }: WelcomeHedgehogProps): JSX.Element {
    console.log(showWelcomeMessage)
    return (
        <div className="welcome-hedgehog-container">
            <img src={hedgehogMain} className="welcome-hedgehog-image" />
            <div className={clsx('welcome-message', !showWelcomeMessage && 'hidden')}>
                <p className="title-text">Welcome to PostHog!</p>
                <p className="secondary-title-text">We're glad to have you here! Let's get started!</p>
            </div>
        </div>
    )
}
