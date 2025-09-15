import './BridgePage.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import { useState } from 'react'
import { CSSTransition } from 'react-transition-group'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { WelcomeLogo } from 'scenes/authentication/WelcomeLogo'

import { Region } from '~/types'

import { LaptopHog4, LaptopHogEU } from '../hedgehogs'

export type BridgePageCommonProps = {
    children?: React.ReactNode
    footer?: React.ReactNode
    header?: React.ReactNode
    view: string
    noLogo?: boolean
    sideLogo?: boolean
    fixedWidth?: boolean
    leftContainerContent?: JSX.Element
}

interface NoHedgehogProps extends BridgePageCommonProps {
    hedgehog?: false
    message?: never
}

interface YesHedgehogProps extends BridgePageCommonProps {
    hedgehog: true
    message?: React.ReactNode
}

// Only allow setting of the hog message when a hog actually exists
type BridgePageProps = NoHedgehogProps | YesHedgehogProps

export function BridgePage({
    children,
    header,
    footer,
    view,
    message,
    noLogo = false,
    sideLogo = false,
    fixedWidth = true,
    leftContainerContent,
    hedgehog = false,
}: BridgePageProps): JSX.Element {
    const [messageShowing, setMessageShowing] = useState(false)
    const { preflight } = useValues(preflightLogic)

    useOnMountEffect(() => {
        const t = setTimeout(() => {
            setMessageShowing(true)
        }, 200)

        return () => clearTimeout(t)
    })

    return (
        <div className={clsx('BridgePage', fixedWidth && 'BridgePage--fixed-width')}>
            <div className="BridgePage__main">
                {leftContainerContent || hedgehog ? (
                    <div className="BridgePage__left-wrapper">
                        <div className="BridgePage__left">
                            {!noLogo && sideLogo && (
                                <div className="BridgePage__header-logo mb-16">
                                    <WelcomeLogo view={view} />
                                </div>
                            )}
                            {leftContainerContent}
                            {hedgehog && (
                                <div className="BridgePage__left__art">
                                    {preflight?.region === Region.EU ? (
                                        <LaptopHogEU alt="" draggable="false" />
                                    ) : (
                                        <LaptopHog4 alt="" draggable="false" />
                                    )}
                                    {message ? (
                                        <CSSTransition
                                            in={messageShowing}
                                            timeout={200}
                                            classNames="BridgePage__left__message-"
                                        >
                                            <div className="BridgePage__left__message">{message}</div>
                                        </CSSTransition>
                                    ) : null}
                                </div>
                            )}
                        </div>
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
            {footer && <div className="BridgePage__footer">{footer}</div>}
        </div>
    )
}
