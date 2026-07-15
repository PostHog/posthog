import { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { OrganizationMembershipLevel } from 'lib/constants'
import { App } from 'scenes/App'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { HeatmapType } from '~/types'

import { HeatmapCreationStep, HeatmapPageAccess, heatmapCreationLogic } from './heatmapCreationLogic'
import { heatmapLogic } from './heatmapLogic'

interface HeatmapNewStoryProps {
    captureEnabled: boolean
    membershipLevel: OrganizationMembershipLevel
    step: HeatmapCreationStep
    pageAccess?: HeatmapPageAccess
    backgroundType?: HeatmapType
    authorizedUrls?: string[]
    recordingBackgroundSelected?: boolean
}

function HeatmapNewStory({
    captureEnabled,
    membershipLevel,
    step,
    pageAccess,
    backgroundType = 'screenshot',
    authorizedUrls = [],
    recordingBackgroundSelected = false,
}: HeatmapNewStoryProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { loadCurrentTeamSuccess } = useActions(teamLogic)
    const { setDisplayUrl, setType } = useActions(heatmapLogic({ id: 'new' }))
    const { applyStep, selectRecordingBackground, setPageAccess } = useActions(heatmapCreationLogic)
    const configuredTeam = useRef(false)
    const configuredWizard = useRef(false)

    useEffect(() => {
        if (currentTeam && !configuredTeam.current) {
            configuredTeam.current = true
            loadCurrentTeamSuccess({
                ...currentTeam,
                heatmaps_opt_in: captureEnabled,
                effective_membership_level: membershipLevel,
                app_urls: authorizedUrls,
            })
        }
    }, [authorizedUrls, captureEnabled, currentTeam, loadCurrentTeamSuccess, membershipLevel])

    useEffect(() => {
        if (configuredWizard.current) {
            return
        }
        configuredWizard.current = true
        setDisplayUrl('https://example.com/pricing')
        setType(backgroundType)
        if (pageAccess) {
            setPageAccess(pageAccess)
        }
        if (recordingBackgroundSelected) {
            const storageKey = 'storybook-recording-background'
            localStorage.setItem(
                storageKey,
                JSON.stringify({
                    html: '<html><body style="margin:0;font-family:sans-serif;background:#f5f5f5"><main style="padding:48px"><h1>Signed-in account dashboard</h1><p>This is the page state selected from the session recording.</p><section style="margin-top:32px;padding:32px;background:white;border:1px solid #ddd;border-radius:8px"><h2>Workspace overview</h2><p>42 active projects</p></section></main></body></html>',
                    width: 1280,
                    height: 720,
                    url: 'https://example.com/pricing',
                })
            )
            selectRecordingBackground(storageKey, 2)
        }
        applyStep(step)
    }, [
        applyStep,
        backgroundType,
        pageAccess,
        recordingBackgroundSelected,
        selectRecordingBackground,
        setDisplayUrl,
        setPageAccess,
        setType,
        step,
    ])

    return <App />
}

const queryMock =
    (matchingCount: number) =>
    async ({ request }: { request: Request }): Promise<[number, Record<string, unknown>]> => {
        const body = (await request.json()) as { query?: { query?: string } }
        const query = body.query?.query ?? ''
        return query.includes('FROM heatmaps')
            ? [200, { results: [[matchingCount]] }]
            : [200, { results: [['https://example.com/pricing', 120]] }]
    }

const meta: Meta<typeof HeatmapNewStory> = {
    component: HeatmapNewStory,
    title: 'Scenes-App/Heatmap New',
    args: {
        captureEnabled: true,
        membershipLevel: OrganizationMembershipLevel.Admin,
        step: 'page',
    },
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        pageUrl: urls.heatmapNew ? urls.heatmapNew() : urls.heatmap('new'),
        testOptions: {
            waitForLoadersToDisappear: true,
        },
        msw: {
            mocks: {
                post: {
                    '/api/environments/:team_id/query/:kind': queryMock(24),
                },
            },
        },
    },
    decorators: [mswDecorator({})],
}
export default meta

type Story = StoryObj<typeof HeatmapNewStory>

export const CaptureDisabledAdmin: Story = {
    args: {
        captureEnabled: false,
        membershipLevel: OrganizationMembershipLevel.Admin,
    },
}

export const CaptureDisabledMember: Story = {
    args: {
        captureEnabled: false,
        membershipLevel: OrganizationMembershipLevel.Member,
    },
}

export const NoMatchingData: Story = {
    parameters: {
        msw: {
            mocks: {
                post: {
                    '/api/environments/:team_id/query/:kind': queryMock(0),
                },
            },
        },
    },
}

export const PublicScreenshot: Story = {
    args: {
        step: 'background',
        pageAccess: 'public',
        backgroundType: 'screenshot',
    },
}

export const UnauthorizedIframe: Story = {
    args: {
        step: 'background',
        pageAccess: 'public',
        backgroundType: 'iframe',
        authorizedUrls: [],
    },
}

export const AuthenticatedWithRecordings: Story = {
    args: {
        step: 'background',
        pageAccess: 'login',
    },
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/environments/:team_id/session_recordings': [
                        200,
                        {
                            results: [
                                {
                                    id: 'recording-one',
                                    start_time: '2026-07-13T17:30:00Z',
                                    recording_duration: 125,
                                },
                                {
                                    id: 'recording-two',
                                    start_time: '2026-07-12T15:00:00Z',
                                    recording_duration: 48,
                                },
                            ],
                        },
                    ],
                },
            },
        },
    },
}

export const AuthenticatedWithoutRecordings: Story = {
    args: {
        step: 'background',
        pageAccess: 'login',
    },
}

export const Review: Story = {
    args: {
        step: 'review',
        pageAccess: 'public',
        backgroundType: 'screenshot',
    },
}

export const AuthenticatedReview: Story = {
    args: {
        step: 'review',
        pageAccess: 'login',
        recordingBackgroundSelected: true,
    },
}
