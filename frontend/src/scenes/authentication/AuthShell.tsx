import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import twigAuthBg from 'public/twig-auth-bg.png'

import { TwigAuthLeftPanel } from './TwigAuthLeftPanel'

interface AuthShellProps {
    view: string
    children: ReactNode
    header?: ReactNode
    footer?: ReactNode
    message?: ReactNode
    leftContainerContent?: JSX.Element
    fixedWidth?: boolean
    sideLogo?: boolean
    showHedgehog?: boolean
    hideFooterForTwig?: boolean
}

export function AuthShell({
    view,
    children,
    header,
    footer,
    message,
    leftContainerContent,
    fixedWidth,
    sideLogo,
    showHedgehog,
    hideFooterForTwig,
}: AuthShellProps): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const isTwig = preflight?.auth_brand === 'twig'

    if (isTwig) {
        return (
            <BridgePage
                view={view}
                noLogo
                theme="twig"
                header={header}
                footer={hideFooterForTwig ? undefined : footer}
                leftContainerContent={<TwigAuthLeftPanel />}
                fixedWidth={fixedWidth}
                sideLogo={false}
                style={{
                    backgroundImage: `url(${twigAuthBg})`,
                }}
            >
                {children}
            </BridgePage>
        )
    }

    return showHedgehog ? (
        <BridgePage
            view={view}
            header={header}
            footer={footer}
            leftContainerContent={leftContainerContent}
            fixedWidth={fixedWidth}
            sideLogo={sideLogo}
            hedgehog={true}
            message={message}
        >
            {children}
        </BridgePage>
    ) : (
        <BridgePage
            view={view}
            header={header}
            footer={footer}
            leftContainerContent={leftContainerContent}
            fixedWidth={fixedWidth}
            sideLogo={sideLogo}
        >
            {children}
        </BridgePage>
    )
}
