import clsx from 'clsx'
import type { ReactNode } from 'react'

import * as magnifyingGlass from '@posthog/brand/hoggies/png/magnifying-glass'
import * as stampDenied from '@posthog/brand/hoggies/png/stamp-denied'
import { IconWarning } from '@posthog/icons'
import {
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    IconStack,
    IconStackItem,
} from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'

const HedgehogSearching = pngHoggie(magnifyingGlass)
const HedgehogDenied = pngHoggie(stampDenied)

export type UnavailableReason = 'notFound' | 'noAccess' | 'error'

type ProblemView = {
    illustration: ReactNode
    title: ReactNode
    description: ReactNode
}

const DEFAULT_VIEWS: Record<UnavailableReason, ProblemView> = {
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
    error: {
        illustration: (
            <IconStack>
                <IconStackItem color="var(--destructive-foreground)">
                    <IconWarning />
                </IconStackItem>
            </IconStack>
        ),
        title: "This dashboard couldn't be shown",
        description: 'Refresh the page, and if it keeps happening contact support.',
    },
}

export type DashboardUnavailableProps = Partial<ProblemView> & {
    problem: UnavailableReason
    /** Buttons or links for the next step, such as going back to a list. The default view has none. */
    actions?: ReactNode
    className?: string
}

/**
 * What a host renders in place of `DashboardView` when the dashboard can't load. Each slot replaces the default for
 * that problem, so a product can change only the words, or add its own next step.
 */
export function DashboardUnavailable({
    problem,
    illustration,
    title,
    description,
    actions,
    className,
}: DashboardUnavailableProps): JSX.Element {
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
