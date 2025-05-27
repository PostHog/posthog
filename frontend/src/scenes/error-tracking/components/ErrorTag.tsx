import { LemonTag } from '@posthog/lemon-ui'
import { cva } from 'cva'

export interface ErrorTagProps {
    label: string
    color: 'yellow' | 'red' | 'blue'
}

const errorTag = cva({
    base: 'font-semibold text-white border-gray-100/20 px-1 py-[0.1rem] text-[11px] rounded-sm inline',
    variants: {
        color: {
            yellow: 'bg-brand-yellow',
            red: 'bg-brand-red',
            blue: 'bg-brand-blue',
        },
    },
})

export function ErrorTag({ color, label }: ErrorTagProps): JSX.Element {
    return (
        <LemonTag size="small" className={errorTag({ color })}>
            {label}
        </LemonTag>
    )
}
