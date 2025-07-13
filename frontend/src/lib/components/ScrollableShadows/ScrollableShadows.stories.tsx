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
                className="border rounded w-200 resize"
                innerClassName="p-4"
                direction="horizontal"
                scrollRef={scrollRef}
            >
                <div className="flex gap-2 items-center">
                    {Array.from({ length: 100 }).map((_, index) => (
                        <div key={index} className="w-24 h-24 shrink-0 bg-accent rounded" />
                    ))}
                </div>
            </ScrollableShadows>
            <div className="flex gap-2 mt-4">
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
                className="border rounded w-60 h-100 resize"
                innerClassName="p-4"
                direction="vertical"
                scrollRef={scrollRef}
            >
                <div className="flex flex-col gap-2 items-center">
                    {Array.from({ length: 100 }).map((_, index) => (
                        <div key={index} className="w-24 h-24 shrink-0 bg-accent rounded" />
                    ))}
                </div>
            </ScrollableShadows>
            <div className="flex gap-2 mt-4">
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
