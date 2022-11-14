import clsx from 'clsx'
import { useEffect, useState } from 'react'
import { WelcomeLogo } from 'scenes/authentication/WelcomeLogo'
import { CSSTransition } from 'react-transition-group'
import './BridgePage.scss'
import { LaptopHog3 } from '../hedgehogs'
import { Link } from '../Link'
import { useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { router } from 'kea-router'
import { Region } from '~/types'
import { CLOUD_HOSTNAMES } from 'lib/constants'

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
    showSignupCta?: boolean
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
    showSignupCta = false,
}: BridgePageProps): JSX.Element {
    const [messageShowing, setMessageShowing] = useState(false)
    const { preflight } = useValues(preflightLogic)

    useEffect(() => {
        const t = setTimeout(() => {
            setMessageShowing(true)
        }, 200)
        return () => clearTimeout(t)
    }, [])

    const getRegionUrl = (region: string): string => {
        const { pathname, search, hash } = router.values.currentLocation
        return `https://${CLOUD_HOSTNAMES[region]}${pathname}${search}${hash}`
    }

    return (
        <div className={clsx('BridgePage', fixedWidth && 'BridgePage--fixed-width', className)}>
            <div className="BridgePage__main">
                {!noHedgehog ? (
                    <div className="BridgePage__art-wrapper">
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
                        </div>
                        {showSignupCta && (
                            <div className="BridgePage__cta border rounded p-4 mt-8 text-center">
                                Did you know?
                                {preflight?.cloud ? (
                                    <span>
                                        {' '}
                                        You can{' '}
                                        <Link to="https://posthog.com/docs/self-host">
                                            <strong>self-host PostHog</strong>
                                        </Link>{' '}
                                        or{' '}
                                        <Link
                                            to={getRegionUrl(preflight?.region === Region.EU ? Region.US : Region.EU)}
                                        >
                                            <strong>
                                                use our {preflight?.region === Region.EU ? 'US' : 'EU'} cloud
                                            </strong>
                                        </Link>
                                        .
                                    </span>
                                ) : (
                                    <span>
                                        {' '}
                                        You can use our{' '}
                                        <Link to={getRegionUrl(Region.EU)}>
                                            <strong>{Region.EU} cloud</strong>
                                        </Link>{' '}
                                        or{' '}
                                        <Link to={getRegionUrl(Region.US)}>
                                            <strong>{Region.US} cloud</strong>
                                        </Link>{' '}
                                        and we'll take care of the hosting for you.
                                    </span>
                                )}
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
