import { Meta } from '@storybook/react'
import { useRef } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { ScrollableShadows } from './ScrollableShadows'

const meta: Meta<typeof ScrollableShadows> = {
    title: 'Lemon UI/Scrollable Shadows',
    component: ScrollableShadows,
    tags: ['autodocs'],
}
export default meta

export const Horizontal = (): JSX.Element => {
    const scrollRef = useRef<HTMLDivElement | null>(null)

    return (
        <>
            <ScrollableShadows
                className="w-200 resize rounded border"
                innerClassName="p-4"
                direction="horizontal"
                scrollRef={scrollRef}
            >
                <div className="flex items-center gap-2">
                    {Array.from({ length: 100 }).map((_, index) => (
                        <div key={index} className="bg-accent h-24 w-24 shrink-0 rounded" />
                    ))}
                </div>
            </ScrollableShadows>
            <div className="mt-4 flex gap-2">
                <LemonButton
                    onClick={() => {
                        scrollRef.current?.scrollBy({ left: -100, behavior: 'smooth' })
                    }}
                >
                    Scroll Left
                </LemonButton>
                <LemonButton
                    onClick={() => {
                        scrollRef.current?.scrollBy({ left: 100, behavior: 'smooth' })
                    }}
                >
                    Scroll Right
                </LemonButton>
            </div>
        </>
    )
}

export const Vertical = (): JSX.Element => {
    const scrollRef = useRef<HTMLDivElement | null>(null)

    return (
        <>
            <ScrollableShadows
                className="h-100 w-60 resize rounded border"
                innerClassName="p-4"
                direction="vertical"
                scrollRef={scrollRef}
            >
                <div className="flex flex-col items-center gap-2">
                    {Array.from({ length: 100 }).map((_, index) => (
                        <div key={index} className="bg-accent h-24 w-24 shrink-0 rounded" />
                    ))}
                </div>
            </ScrollableShadows>
            <div className="mt-4 flex gap-2">
                <LemonButton
                    onClick={() => {
                        scrollRef.current?.scrollBy({ top: -100, behavior: 'smooth' })
                    }}
                >
                    Scroll Up
                </LemonButton>
                <LemonButton
                    onClick={() => {
                        scrollRef.current?.scrollBy({ top: 100, behavior: 'smooth' })
                    }}
                >
                    Scroll Down
                </LemonButton>
            </div>
        </>
    )
}
