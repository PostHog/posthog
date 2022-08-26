import clsx from 'clsx'
import React, { useEffect, useState } from 'react'
import { WelcomeLogo } from 'scenes/authentication/WelcomeLogo'
import hedgehogMain from 'public/hedgehog-bridge-page.png'
import { CSSTransition } from 'react-transition-group'
import './BridgePage.scss'

export type BridgePageProps = {
    className?: string
    children?: React.ReactNode
    footer?: React.ReactNode
    view: string
    noHedgehog?: boolean
    message?: React.ReactNode
    fixedWidth?: boolean
}

export function BridgePage({
    children,
    className,
    footer,
    view,
    message,
    noHedgehog = false,
    fixedWidth = true,
}: BridgePageProps): JSX.Element {
    const [messageShowing, setMessageShowing] = useState(false)

    useEffect(() => {
        const t = setTimeout(() => {
            setMessageShowing(true)
        }, 200)
        return () => clearTimeout(t)
    }, [])
    return (
        <div className={clsx('BridgePage', fixedWidth && 'BridgePage--fixed-width', className)}>
            <div className="BridgePage__main">
                {!noHedgehog ? (
                    <div className="BridgePage__art">
                        <img src={hedgehogMain} alt="" draggable="false" />
                        {message ? (
                            <CSSTransition in={messageShowing} timeout={200} classNames="BridgePage__art__message-">
                                <div className="BridgePage__art__message">{message}</div>
                            </CSSTransition>
                        ) : null}
                    </div>
                ) : null}
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
