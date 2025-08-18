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
