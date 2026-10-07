import clsx from 'clsx'
import { useState } from 'react'

import { IconFilter } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'

export interface FilterBarProps {
    top?: React.ReactNode
    left?: React.ReactNode
    right?: React.ReactNode
    className?: string
    showBorderBottom?: boolean
}

export const FilterBar = ({ top, left, right, className, showBorderBottom }: FilterBarProps): JSX.Element => {
    const [expanded, setExpanded] = useState(false)

    return (
        <SceneStickyBar className={className} showBorderBottom={showBorderBottom}>
            {top}

            <div className="flex flex-col md:flex-row md:justify-between gap-2">
                <div className={clsx('flex items-start shrink-0', !right && 'flex-1')}>
                    <div className="flex flex-1 flex-row gap-2 items-start">
                        <div
                            className={clsx(
                                'flex flex-row flex-wrap gap-1 items-center flex-1',
                                right && 'md:flex-none'
                            )}
                        >
                            {left}
                        </div>

                        {right && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                className="sm:hidden"
                                active={expanded}
                                onClick={() => setExpanded((expanded) => !expanded)}
                                icon={<IconFilter />}
                                aria-label={expanded ? 'Hide filters' : 'Show filters'}
                                aria-expanded={expanded}
                            />
                        )}
                    </div>
                </div>

                {/* Render right content once - on mobile it's collapsible, on sm+ always visible */}
                {right && (
                    <div
                        className={clsx(
                            'flex gap-2',
                            'sm:max-h-none',
                            'max-sm:flex-col max-sm:overflow-hidden max-sm:transition-all max-sm:duration-200',
                            expanded ? 'max-sm:max-h-[500px]' : 'max-sm:max-h-0 max-sm:-mt-2'
                        )}
                    >
                        <FoldableFilters>{right}</FoldableFilters>
                    </div>
                )}
            </div>
        </SceneStickyBar>
    )
}

const FoldableFilters = ({ children }: React.PropsWithChildren<{}>): JSX.Element => {
    return (
        <div className="flex flex-row md:flex-row-reverse flex-wrap gap-2 md:[&>*]:grow-0 [&>*]:grow [&>.LemonButton--no-content]:grow-0 w-full items-start">
            {children}
        </div>
    )
}
