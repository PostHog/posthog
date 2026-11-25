import clsx from 'clsx'
import type { ReactNode } from 'react'

import * as magnifyingGlass from '@posthog/brand/hoggies/png/magnifying-glass'
import * as stampDenied from '@posthog/brand/hoggies/png/stamp-denied'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'

const HedgehogSearching = pngHoggie(magnifyingGlass)
const HedgehogDenied = pngHoggie(stampDenied)

export type DashboardV2Problem = 'notFound' | 'noAccess'

interface ProblemView {
    illustration: ReactNode
    title: ReactNode
    description: ReactNode
}

const DEFAULT_VIEWS: Record<DashboardV2Problem, ProblemView> = {
    notFound: {
        illustration: <HedgehogSearching />,
        title: 'Dashboard not found',
        description: 'It may have been deleted, or the link is wrong. Check the link or go back to your dashboards.',
    },
    noAccess: {
        illustration: <HedgehogDenied />,
        title: "You don't have access to this dashboard",
        description: 'Ask the dashboard owner or a project admin to give you access.',
    },
}

export interface DashboardV2UnavailableProps extends Partial<ProblemView> {
    problem: DashboardV2Problem
    /** Buttons or links for the next step, such as going back to a list. The default view has none. */
    actions?: ReactNode
    className?: string
}

/**
 * What a host renders in place of `DashboardV2View` when the dashboard can't load. Each slot replaces the default for
 * that problem, so a product can change only the words, or add its own next step.
 */
export function DashboardV2Unavailable({
    problem,
    illustration,
    title,
    description,
    actions,
    className,
}: DashboardV2UnavailableProps): JSX.Element {
    const defaults = DEFAULT_VIEWS[problem]
    return (
        <Empty className={clsx('h-full', className)} data-attr={`dashboard-v2-unavailable-${problem}`}>
            <EmptyHeader>
                <EmptyMedia className="[&_img]:size-32">{illustration ?? defaults.illustration}</EmptyMedia>
                <EmptyTitle>{title ?? defaults.title}</EmptyTitle>
                <EmptyDescription>{description ?? defaults.description}</EmptyDescription>
            </EmptyHeader>
            {actions && <EmptyContent>{actions}</EmptyContent>}
        </Empty>
    )
}
