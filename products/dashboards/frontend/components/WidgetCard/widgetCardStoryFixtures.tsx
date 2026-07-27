import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import type { Decorator } from '@storybook/react'
import React from 'react'

import { CardTopHeadingRow } from 'lib/components/Cards/CardTopHeadingRow'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenuOverlay, type LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'

import { exceptionIngestionLogic } from 'products/error_tracking/frontend/components/SetupPrompt/exceptionIngestionLogic'

import { WidgetCardContent, WidgetContentFooter } from './WidgetCardBody'

export const TILE_WIDTH = 560
export const TILE_HEIGHT = 480

/** Freeze Storybook/VR "now" — keeps relative dates stable. Matches fixture timestamps in widgetOverviewStoryFixtures. */
export const WIDGET_STORYBOOK_MOCK_DATE = '2026-05-26T10:00:00'

/** Spread into story `parameters` so `withMockDate` pins TZLabel / relative copy in VR snapshots. */
export const widgetStorybookParameters = {
    mockDate: WIDGET_STORYBOOK_MOCK_DATE,
} as const

export function WidgetTileFrame({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div
            className="rounded border border-dashed border-border bg-bg-light p-4"
            style={{ width: TILE_WIDTH, height: TILE_HEIGHT }}
        >
            <div className="h-full min-h-0">{children}</div>
        </div>
    )
}

export const widgetTileFrameDecorator = [
    (Story: React.ComponentType): JSX.Element => (
        <WidgetTileFrame>
            <Story />
        </WidgetTileFrame>
    ),
]

/** Realistic dashboard widget ⋯ menu for Storybook — flat LemonMenu items, not bordered buttons. */
export const mockWidgetMoreMenuItems: LemonMenuItems = [
    { label: 'View', to: '/error_tracking' },
    { label: 'Edit', onClick: () => undefined },
    { label: 'Duplicate', onClick: () => undefined },
    {
        title: 'Dashboard',
        items: [
            { label: 'Hide description', onClick: () => undefined },
            { label: 'Remove from dashboard', status: 'danger', onClick: () => undefined },
        ],
    },
    { label: 'Refresh data', onClick: () => undefined },
]

export const mockMoreOverlay = <LemonMenuOverlay items={mockWidgetMoreMenuItems} />

export const sampleListBody = (
    <>
        <WidgetCardContent>
            <ul className="m-0 flex list-none flex-col gap-3 p-0 text-sm">
                <li className="rounded border border-primary p-3">
                    <div className="font-semibold">Homepage visits</div>
                    <div className="text-muted">12,480 events · 3,210 users</div>
                </li>
                <li className="rounded border border-primary p-3">
                    <div className="font-semibold">Signup conversion</div>
                    <div className="text-muted">842 events · 612 users</div>
                </li>
                <li className="rounded border border-primary p-3">
                    <div className="font-semibold">Weekly active users</div>
                    <div className="text-muted">4,102 users · +8% vs last week</div>
                </li>
            </ul>
        </WidgetCardContent>
        <WidgetContentFooter>
            <LemonButton type="secondary" size="small">
                View all
            </LemonButton>
        </WidgetContentFooter>
    </>
)

export const dashboardTileTopHeading = <CardTopHeadingRow typeLabel="Analytics" showTypeLabel dateText="Last 7 days" />

export function seedErrorTrackingProjectState(configured: boolean): void {
    teamLogic.mount()
    filterTestAccountsDefaultsLogic.mount()
    teamLogic.actions.loadCurrentTeamSuccess({
        ...MOCK_DEFAULT_TEAM,
        autocapture_exceptions_opt_in: configured,
    })

    exceptionIngestionLogic.mount()
    exceptionIngestionLogic.actions.loadExceptionIngestionStateSuccess(configured)
}

/** Configured = issues can be queried (post setup). Unconfigured = ingestion prompt / settings hidden. */
export function withErrorTrackingProjectState(configured: boolean): Decorator {
    return (Story: React.ComponentType): JSX.Element => {
        seedErrorTrackingProjectState(configured)
        return <Story />
    }
}

/** Configured = session replay enabled for the project. Unconfigured = availability setup prompt. */
export function withSessionReplayProjectState(enabled: boolean): Decorator {
    return (Story: React.ComponentType): JSX.Element => {
        teamLogic.mount()
        filterTestAccountsDefaultsLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            session_recording_opt_in: enabled,
        })
        return <Story />
    }
}
