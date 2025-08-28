import clsx from 'clsx'
import { useState } from 'react'

import { IconFilter } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

export interface FilterBarProps {
    top?: React.ReactNode
    left?: React.ReactNode
    right?: React.ReactNode
}

export const FilterBar = ({ top, left, right }: FilterBarProps): JSX.Element => {
    const [expanded, setExpanded] = useState(false)

    return (
        <div className="sticky z-20 bg-primary border-b py-2 top-[var(--breadcrumbs-height-compact)]">
            {top}

            <div className="flex flex-col md:flex-row md:justify-between gap-2">
                <div className="flex items-start shrink-0">
                    <div className="flex flex-1 flex-row gap-2 items-center">
                        <div className="flex flex-row gap-1 items-center flex-1 md:flex-none">{left}</div>

                        <LemonButton
                            type="secondary"
                            size="small"
                            className="sm:hidden"
                            onClick={() => setExpanded((expanded) => !expanded)}
                            icon={<IconFilter />}
                        />
                    </div>
                </div>

                {/* On more than mobile, just display Foldable Fields, on smaller delegate displaying it to the expanded state */}
                <div className="hidden sm:flex gap-2">
                    <FoldableFilters>{right}</FoldableFilters>
                </div>

                <div
                    className={clsx(
                        'flex sm:hidden flex-col gap-2 overflow-hidden transition-all duration-200',
                        expanded ? 'max-h-[500px]' : 'max-h-0'
                    )}
                >
                    <FoldableFilters>{right}</FoldableFilters>
                </div>
            </div>
        </div>
    )
}

const FoldableFilters = ({ children }: React.PropsWithChildren<{}>): JSX.Element => {
    return (
        <div className="flex flex-row md:flex-row-reverse flex-wrap gap-2 md:[&>*]:grow-0 [&>*]:grow w-full">
            {children}
        </div>
    )
}
