import type { ReactNode } from 'react'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'

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
}: AuthShellProps): JSX.Element {
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
