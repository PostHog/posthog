import { LemonButton } from '@posthog/lemon-ui'
import React from 'react'

export default {
    title: 'Lemon UI/Utilities',
}

export const Overview = (): JSX.Element => {
    // TODO: I should be fleshed out using this example to describe when utilities should and should not be used...
    return (
        <div className="space-y">
            <div className="rounded-lg border space-y">
                <div className="p-4 border-b">
                    <div className="text-lg font-bold">Hello there!</div>
                    <div className="text-sm">
                        I'm an example of how you can use utility classes to build a{' '}
                        <span className="text-primary">complex component</span> without any custom CSS...
                    </div>
                </div>

                <div className="flex justify-end gap-2 m-2">
                    <LemonButton type="secondary">It's really...</LemonButton>
                    <LemonButton type="primary">Amazing!</LemonButton>
                </div>
            </div>
        </div>
    )
}

export const Flex = (): JSX.Element => {
    return (
        <div className="space-y-2">
            <div className="border rounded-lg p-2">
                <div className="flex items-center justify-between gap-2">
                    <LemonButton type="primary">Button!</LemonButton>
                    <span>I am vertically centered!</span>
                </div>
            </div>

            <div className="border rounded-lg p-2">
                <div className="flex items-end justify-end gap-2">
                    <LemonButton type="primary">Button!</LemonButton>
                    <span>I am bottom aligned!</span>
                </div>
            </div>
        </div>
    )
}

export const SpaceAndGap = (): JSX.Element => {
    return (
        <div className="space-y-2">
            <p>
                Use <code>space-y/x-</code> for non-flexed items
                <br />
                For flex items use <code>gap-</code> to space items
            </p>
            <div className="flex items-center gap-2">
                <LemonButton type="primary">Button</LemonButton>
                <LemonButton type="primary">Button</LemonButton>
                <LemonButton type="primary">Button</LemonButton>
                <code>gap-2 (0.5rem or 8px)</code>
            </div>

            <div className="flex items-center gap-4">
                <LemonButton type="primary">Button</LemonButton>
                <LemonButton type="primary">Button</LemonButton>
                <LemonButton type="primary">Button</LemonButton>
                <code>gap-4 (1rem or 16px)</code>
            </div>

            <div className="flex items-center gap-8">
                <LemonButton type="primary">Button</LemonButton>
                <LemonButton type="primary">Button</LemonButton>
                <LemonButton type="primary">Button</LemonButton>
                <code>gap-8 (2rem or 32px)</code>
            </div>
        </div>
    )
}

export const IndividualSpacing = (): JSX.Element => {
    return (
        <>
            <p>
                If really necessary you can space individual elements using <code>m</code> or <code>p</code> utilities.
            </p>
            <div className="flex">
                <span className="mr-2">
                    <LemonButton type="primary">Button</LemonButton>
                </span>
                <span className="mr-4">
                    <LemonButton type="primary">Button</LemonButton>
                </span>
                <span className="ml-8">
                    <LemonButton type="primary">Button</LemonButton>
                </span>
            </div>
        </>
    )
}

export const Dimensions = (): JSX.Element => {
    return (
        <>
            <p>
                Some standard small widths and heights are available as utilities. If you need a very specific width or
                height you should be using CSS / style
            </p>

            <div className="space-y-2">
                {[8, 16, 20, 'full', 'screen'].map((x) => (
                    <div key={x} className={`border rounded-lg p-2 w-${x}`}>
                        w-{x}
                    </div>
                ))}
            </div>
        </>
    )
}

export const TextSize = (): JSX.Element => {
    return (
        <>
            {['xxs', 'xs', 'sm', 'base', 'lg', 'xl', '2xl', '3xl', '4xl', '5xl', '6xl', '7xl', '8xl', '9xl'].map(
                (x) => (
                    <p key={x} className={`text-${x}`}>
                        text-{x}
                    </p>
                )
            )}
        </>
    )
}

export const TextFont = (): JSX.Element => {
    return (
        <>
            <p className="font-sans">font-sans (default)</p>
            <p className="font-mono">font-mono</p>
        </>
    )
}

export const TextWeight = (): JSX.Element => {
    return (
        <>
            <p className="font-thin">font-thin</p>
            <p className="font-extralight">font-extralight</p>
            <p className="font-light">font-light</p>
            <p className="font-normal">font-normal</p>
            <p className="font-medium">font-medium</p>
            <p className="font-semibold">font-semibold</p>
            <p className="font-bold">font-bold</p>
            <p className="font-extrabold">font-extrabold</p>
            <p className="font-black">font-black</p>
        </>
    )
}
