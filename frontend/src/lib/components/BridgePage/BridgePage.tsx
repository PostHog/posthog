import clsx from 'clsx'
import React from 'react'
import { WelcomeLogo } from 'scenes/authentication/WelcomeLogo'
import hedgehogMain from 'public/hedgehog-bridge-page.png'
import './BridgePage.scss'

export type BridgePageProps = {
    className?: string
    children?: React.ReactNode
    footer?: React.ReactNode
    view: string
}

export function BridgePage({ children, className, footer, view }: BridgePageProps): JSX.Element {
    return (
        <div className={clsx('BridgePage', className)}>
            <img src={hedgehogMain} alt="" className="BridgePage__art" />
            <div className="BridgePage__content-wrapper">
                <WelcomeLogo view={view} />
                <div className="BridgePage__content">
                    {children}
                    <div className="BridgePage__footer">{footer}</div>
                </div>
            </div>
        </div>
    )
}
