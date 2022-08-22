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
    noHedgehog?: boolean
}

export function BridgePage({ children, className, footer, view, noHedgehog = false }: BridgePageProps): JSX.Element {
    return (
        <div className={clsx('BridgePage', className)}>
            <div className="BridgePage__main">
                {!noHedgehog ? <img src={hedgehogMain} alt="" className="BridgePage__art" /> : null}
                <div className="BridgePage__content-wrapper">
                    <div className="BridgePage__header-logo">
                        <WelcomeLogo view={view} />
                    </div>
                    <div className="BridgePage__content">{children}</div>
                </div>
            </div>
            <div className="BridgePage__footer">{footer}</div>
        </div>
    )
}
