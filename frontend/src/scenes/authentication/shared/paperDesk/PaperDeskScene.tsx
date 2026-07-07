import './PaperDesk.scss'

import { type ReactNode } from 'react'

import { Logo } from 'lib/brand'

import { DevLoginPanel } from './DevLoginPanel'
import { Typewriter } from './Typewriter'

/** Full-viewport paper-desk stage: dotted parchment + accent glow + mono corner notes. */
export function PaperDeskScene({ notes, children }: { notes: string[]; children: ReactNode }): JSX.Element {
    return (
        <div className="PaperDesk relative h-screen overflow-x-hidden overflow-y-auto font-sans text-primary bg-[#eef0e7]">
            <div className="hidden sm:block">
                <Typewriter lines={notes} />
            </div>
            <div className="relative z-[3] flex flex-col items-center justify-center min-h-full py-18 px-4 sm:px-10">
                <div className="PaperDesk__column flex flex-col items-center w-[27rem] max-w-full">{children}</div>
            </div>
            <DevLoginPanel />
        </div>
    )
}

/** Logo (or custom header) + white card + optional footer note — the column contents. */
export function PaperDeskCard({
    top,
    footer,
    children,
}: {
    top?: ReactNode
    footer?: ReactNode
    children: ReactNode
}): JSX.Element {
    return (
        <>
            {top === undefined ? (
                <span className="PaperDesk__logo block mb-4">
                    <Logo variant="gradient" size="lg" />
                </span>
            ) : (
                top
            )}
            <div className="w-full pt-8 px-5 sm:px-9 pb-8 bg-white border border-[#e0e1d9] rounded-lg shadow-[0_20px_44px_-26px_rgb(40_38_30/35%),0_3px_0_#e0e1d9]">
                {children}
            </div>
            {footer}
        </>
    )
}
