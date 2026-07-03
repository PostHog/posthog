import './BridgePage.scss'

import clsx from 'clsx'

import { WelcomeLogo } from 'scenes/authentication/shared/WelcomeLogo'

export type BridgePageProps = {
    children?: React.ReactNode
    footer?: React.ReactNode
    header?: React.ReactNode
    view: string
    noLogo?: boolean
    sideLogo?: boolean
    fixedWidth?: boolean
    leftContainerContent?: JSX.Element
    style?: React.CSSProperties
}

export function BridgePage({
    children,
    header,
    footer,
    view,
    noLogo = false,
    sideLogo = false,
    fixedWidth = true,
    leftContainerContent,
    style,
}: BridgePageProps): JSX.Element {
    return (
        <div className={clsx('BridgePage', fixedWidth && 'BridgePage--fixed-width')} style={style}>
            <div className="BridgePage__main">
                {leftContainerContent ? (
                    <div className="BridgePage__left-wrapper">
                        <div className="BridgePage__left">
                            {!noLogo && sideLogo && (
                                <div className="BridgePage__header-logo mb-16">
                                    <WelcomeLogo view={view} />
                                </div>
                            )}
                            {leftContainerContent}
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
