import type { Meta } from '@storybook/react'

import { ButtonPrimitive } from '../Button/ButtonPrimitives'
import { WrappingLoadingSkeleton } from './WrappingLoadingSkeleton'

const meta = {
    title: 'UI/WrappingLoadingSkeleton',
    component: WrappingLoadingSkeleton as any,
    tags: ['autodocs'],
} satisfies Meta<typeof WrappingLoadingSkeleton>

export default meta

export function Default(): JSX.Element {
    return (
        <div className="flex flex-col gap-4 max-w-lg">
            <p>
                The wrapping loading skeleton will wrap around the children and take the size of the children, making it
                easy to do loading states for any component (as long as you can wrap a copy of it or mimic it)
            </p>
            <WrappingLoadingSkeleton>
                <ButtonPrimitive inert aria-hidden>
                    Some invisible text
                </ButtonPrimitive>
            </WrappingLoadingSkeleton>
            <WrappingLoadingSkeleton>
                <ButtonPrimitive inert aria-hidden>
                    small
                </ButtonPrimitive>
            </WrappingLoadingSkeleton>
        </div>
    )
}

export function Inset(): JSX.Element {
    return (
        <div className="flex flex-col max-w-lg">
            <p className="mb-4">
                The inset prop adds vertical padding so skeletons don't fill their bounds completely. This prevents
                rounded corners from touching when stacked, without causing layout shift when content loads.
            </p>
            <div className="border border-primary rounded p-2">
                <p className="text-xs text-secondary mb-2">Without inset (corners touch):</p>
                {[1, 2, 3].map((i) => (
                    <WrappingLoadingSkeleton key={i} fullWidth>
                        <ButtonPrimitive fullWidth inert aria-hidden>
                            Row {i}
                        </ButtonPrimitive>
                    </WrappingLoadingSkeleton>
                ))}
            </div>
            <div className="border border-primary rounded p-2 mt-4">
                <p className="text-xs text-secondary mb-2">With inset (gaps between rows):</p>
                {[1, 2, 3].map((i) => (
                    <WrappingLoadingSkeleton key={i} fullWidth inset>
                        <ButtonPrimitive fullWidth inert aria-hidden>
                            Row {i}
                        </ButtonPrimitive>
                    </WrappingLoadingSkeleton>
                ))}
            </div>
        </div>
    )
}
