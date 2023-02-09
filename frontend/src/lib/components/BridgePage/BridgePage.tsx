import clsx from 'clsx'
import { useEffect, useState } from 'react'
import { WelcomeLogo } from 'scenes/authentication/WelcomeLogo'
import { CSSTransition } from 'react-transition-group'
import './BridgePage.scss'
import { LaptopHog3 } from '../hedgehogs'

export type BridgePageCommonProps = {
    className?: string
    children?: React.ReactNode
    footer?: React.ReactNode
    header?: React.ReactNode
    view: string
    noLogo?: boolean
    sideLogo?: boolean
    fixedWidth?: boolean
    leftContainerContent?: JSX.Element
    fullScreen?: boolean
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
    className,
    header,
    footer,
    view,
    message,
    noLogo = false,
    sideLogo = false,
    fixedWidth = true,
    leftContainerContent,
    hedgehog = false,
    fullScreen = true,
}: BridgePageProps): JSX.Element {
    const [messageShowing, setMessageShowing] = useState(false)

    useEffect(() => {
        const t = setTimeout(() => {
            setMessageShowing(true)
        }, 200)
        return () => clearTimeout(t)
    }, [])

    return (
        <div
            className={clsx(
                'BridgePage',
                fixedWidth && 'BridgePage--fixed-width',
                fullScreen && 'BridgePage--full-screen',
                className
            )}
        >
            <div className="BridgePage__main">
                {leftContainerContent || hedgehog ? (
                    <div className="BridgePage__left-wrapper">
                        <div className="BridgePage__left">
                            {!noLogo && sideLogo && (
                                <div className="BridgePage__header-logo mb-4">
                                    <WelcomeLogo view={view} />
                                </div>
                            )}
                            {leftContainerContent && leftContainerContent}
                            {hedgehog && (
                                <div className="BridgePage__left__art">
                                    <LaptopHog3 alt="" draggable="false" />
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
            <div className="BridgePage__footer">{footer}</div>
        </div>
    )
}
