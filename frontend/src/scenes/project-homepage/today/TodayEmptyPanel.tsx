import type { ReactNode } from 'react'

export function TodayEmptyPanel({
    message,
    children,
    dataAttr,
}: {
    message: string
    children: ReactNode
    dataAttr: string
}): JSX.Element {
    return (
        <div className="TodayEmptyPanel" data-attr={dataAttr}>
            <div className="TodayEmptyPanel__shapes" aria-hidden>
                {children}
            </div>
            <p className="TodayEmptyPanel__message">
                <span className="TodayEmptyPanel__pill">{message}</span>
            </p>
        </div>
    )
}
