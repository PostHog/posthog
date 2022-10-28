import clsx from 'clsx'
import { useEffect, useState } from 'react'
import { WelcomeLogo } from 'scenes/authentication/WelcomeLogo'
import { CSSTransition } from 'react-transition-group'
import './BridgePage.scss'
import { LaptopHog3 } from '../hedgehogs'

export type BridgePageProps = {
    className?: string
    children?: React.ReactNode
    footer?: React.ReactNode
    header?: React.ReactNode
    view: string
    noHedgehog?: boolean
    noLogo?: boolean
    sideLogo?: boolean
    message?: React.ReactNode
    showSelfHostCta?: boolean
    fixedWidth?: boolean
}

export function BridgePage({
    children,
    className,
    header,
    footer,
    view,
    message,
    noHedgehog = false,
    noLogo = false,
    sideLogo = false,
    fixedWidth = true,
    showSelfHostCta = false,
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
                        {!noLogo && sideLogo && (
                            <div className="BridgePage__header-logo mb-4">
                                <WelcomeLogo view={view} />
                            </div>
                        )}
                        <LaptopHog3 alt="" draggable="false" />
                        {message ? (
                            <CSSTransition in={messageShowing} timeout={200} classNames="BridgePage__art__message-">
                                <div className="BridgePage__art__message">{message}</div>
                            </CSSTransition>
                        ) : null}

                        {showSelfHostCta && (
                            <div
                                style={{
                                    border: '1px solid var(--border)',
                                    borderRadius: 'var(--radius)',
                                    padding: '1rem',
                                    marginTop: '2rem',
                                    textAlign: 'center',
                                }}
                            >
                                Interested in self-hosting PostHog?&nbsp;
                                <a href="https://license.posthog.com">
                                    <strong>Get a license key</strong>
                                </a>
                            </div>
                        )}
                    </div>
                ) : null}
                <div className="BridgePage__content-wrapper">
                    {!noLogo && (
                        <div className={clsx('BridgePage__header-logo', { mobile: sideLogo })}>
                            <WelcomeLogo view={view} />
                        </div>
                    )}
                    <div className="BridgePage__header">{header}</div>
                    <div className="BridgePage__content">{children}</div>
                </div>
            </div>
            <div className="BridgePage__footer">{footer}</div>
        </div>
    )
}
