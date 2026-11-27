import type { ReactNode } from 'react'

import { IconChevronDown } from '@posthog/icons'

import { INCOMPLETE_LABEL } from '../filterDefinition'

export function FilterPillContent({ label, summary }: { label: string; summary?: ReactNode }): JSX.Element {
    return (
        <>
            <span className="text-secondary border-r pr-1.5">{label}</span>
            {summary ?? <span className="text-tertiary">{INCOMPLETE_LABEL}</span>}
            <IconChevronDown />
        </>
    )
}
