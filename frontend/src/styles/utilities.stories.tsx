import { LemonButton } from '@posthog/lemon-ui'
import { Meta } from '@storybook/react'

const meta: Meta = {
    title: 'Lemon UI/Utilities',
    tags: ['autodocs'],
}
export default meta

export const Overview = (): JSX.Element => {
    // TODO: I should be fleshed out using this example to describe when utilities should and should not be used...
    return (
        <div className="space-y">
            <div className="rounded-lg border space-y">
                <div className="p-4 border-b">
                    <div className="text-lg font-bold">Hello there!</div>
                    <div className="text-sm">
                        I'm an example of how you can use utility classes to build a{' '}
                        <span className="text-link">complex component</span> without any custom CSS...
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
                {[8, 10, 20, 'full', 'screen'].map((x) => (
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

export const Widths = (): JSX.Element => {
    return (
        <div className="flex flex-col space-y-2">
            <div className="w-1/5 border rounded text-center">w-1/5</div>
            <div className="w-1/3 border rounded text-center">w-1/3</div>
            <div className="w-2/5 border rounded text-center">w-2/5</div>
            <div className="w-1/2 border rounded text-center">w-1/2</div>
            <div className="w-3/5 border rounded text-center">w-3/5</div>
            <div className="w-2/3 border rounded text-center">w-2/3</div>
            <div className="w-4/5 border rounded text-center">w-4/5</div>
            <div className="w-full border rounded text-center">w-full</div>
        </div>
    )
}
export const Heights = (): JSX.Element => {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div className="flex flex-row space-x-2" style={{ height: '100px' }}>
            <div className="h-1/5 border rounded text-center">h-1/5</div>
            <div className="h-1/3 border rounded text-center">h-1/3</div>
            <div className="h-2/5 border rounded text-center">h-2/5</div>
            <div className="h-1/2 border rounded text-center">h-1/2</div>
            <div className="h-3/5 border rounded text-center">h-3/5</div>
            <div className="h-2/3 border rounded text-center">h-2/3</div>
            <div className="h-4/5 border rounded text-center">h-4/5</div>
            <div className="h-full border rounded text-center">h-full</div>
        </div>
    )
}

export const AbsolutePositioning = (): JSX.Element => {
    return (
        <>
            <p>You can easily position elements absolutely using these classes:</p>
            <div className="text-xs flex flex-col space-y-4">
                <div className="flex space-x-8">
                    <div className="w-20">
                        <div className="relative border h-20 w-20">
                            <div className="absolute border border-primary left-0 top-0 h-10 w-10" />
                        </div>
                        left-0 top-0
                    </div>
                    <div className="w-20">
                        <div className="relative border h-20 w-20">
                            <div className="absolute border border-primary inset-x-0 top-0 h-10 w-10" />
                        </div>
                        inset-x-0 top-0
                    </div>
                    <div className="w-20">
                        <div className="relative border h-20 w-20">
                            <div className="absolute border border-primary top-0 right-0 h-10 w-10" />
                        </div>
                        top-0 right-0
                    </div>
                </div>
                <div className="flex space-x-8">
                    <div className="w-20">
                        <div className="relative border h-20 w-20">
                            <div className="absolute border border-primary inset-y-0 left-0 h-10 w-10" />
                        </div>
                        inset-y-0 left-0
                    </div>
                    <div className="w-20">
                        <div className="relative border h-20 w-20">
                            <div className="absolute border border-primary inset-0" />
                        </div>
                        inset-0
                    </div>
                    <div className="w-20">
                        <div className="relative border h-20 w-20">
                            <div className="absolute border border-primary inset-y-0 right-0 h-10 w-10" />
                        </div>
                        inset-y-0 right-0
                    </div>
                </div>
                <div className="flex space-x-8">
                    <div className="w-20">
                        <div className="relative border h-20 w-20">
                            <div className="absolute border border-primary bottom-0 left-0 h-10 w-10" />
                        </div>
                        bottom-0 left-0
                    </div>
                    <div className="w-20">
                        <div className="relative border h-20 w-20">
                            <div className="absolute border border-primary inset-x-0 bottom-0 h-10 w-10" />
                        </div>
                        inset-x-0 bottom-0
                    </div>
                    <div className="w-20">
                        <div className="relative border h-20 w-20">
                            <div className="absolute border border-primary bottom-0 right-0 h-10 w-10" />
                        </div>
                        bottom-0 right-0
                    </div>
                </div>
            </div>
        </>
    )
}
