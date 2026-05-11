import {
    MOCK_DEFAULT_BASIC_USER,
    MOCK_DEFAULT_ORGANIZATION,
    MOCK_DEFAULT_PROJECT,
    MOCK_DEFAULT_TEAM,
    MOCK_DEFAULT_USER,
    MOCK_ORGANIZATION_ID,
    MOCK_TEAM_ID,
} from 'lib/api.mock'

import { Meta, StoryObj, type Decorator } from '@storybook/react'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DashboardTemplateEditor } from 'scenes/dashboard/DashboardTemplateEditor'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'
import {
    InsightColor,
    type DashboardTemplateType,
    type OrganizationType,
    type ProjectType,
    type TeamType,
    type UserType,
} from '~/types'

import { DashboardTemplateModal } from './DashboardTemplateModal'
import { dashboardTemplatesLogic } from './dashboardTemplatesLogic'
import { DashboardTemplatesTable } from './DashboardTemplatesTable'

/** Same key as `DashboardTemplatesTable` — list load is driven by `/dashboard` urlToAction in-app; storybook calls `getAllTemplates` after mount so the table is not stuck empty. */
const templatesTabListLogic = dashboardTemplatesLogic({ scope: 'default', templatesTabList: true })

const meta: Meta<typeof DashboardTemplatesTable> = {
    title: 'Scenes-App/Dashboards/Templates/Dashboard templates table',
    component: DashboardTemplatesTable,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/dashboard_templates/json_schema/': require('../../__mocks__/dashboard_template_schema.json'),
            },
        }),
        (Story) => (
            <div className="bg-primary min-h-screen w-full p-4">
                <Story />
                <DashboardTemplateEditor />
                <DashboardTemplateModal />
            </div>
        ),
    ],
    parameters: {
        posthogTheme: 'light',
        backgrounds: { default: 'light' },
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: urls.dashboards(),
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
}

export default meta

type Story = StoryObj<typeof DashboardTemplatesTable>

type ViewerMode = 'staff' | 'nonStaff'

const insightTile = {
    type: 'INSIGHT' as const,
    name: 'Weekly signups',
    color: InsightColor.Blue,
    layouts: {},
    query: {
        kind: 'InsightVizNode' as const,
        source: {
            kind: 'TrendsQuery' as const,
            series: [],
            interval: 'day',
            dateRange: { date_from: '-30d' },
        },
    },
}

const textTile = { type: 'TEXT' as const, body: 'Notes', layouts: {} }

/** 30 rows → LemonTable `pageSize: 25` shows page 2 + pagination. Mix: team vs official, featured vs not, tags / no tags / overflow. */
const sampleTemplates: DashboardTemplateType[] = [
    ...Array.from({ length: 10 }, (_, i): DashboardTemplateType => {
        const tagPattern = i % 5
        const tags =
            tagPattern === 0
                ? []
                : tagPattern === 1
                  ? ['ops']
                  : tagPattern === 2
                    ? ['growth', 'saved-view']
                    : tagPattern === 3
                      ? ['internal', 'finance', 'kpi', 'review', 'q1']
                      : ['experiment']

        return {
            id: `tpl-team-${i + 1}`,
            template_name: `Team weekly KPIs ${String(i + 1).padStart(2, '0')}`,
            dashboard_description:
                i % 3 === 0
                    ? 'Project-only template; no tags on every fifth row.'
                    : 'Project-saved dashboard template for this environment.',
            scope: 'team',
            team_id: MOCK_TEAM_ID,
            created_by: MOCK_DEFAULT_BASIC_USER,
            tags,
            dashboard_filters: {},
            variables: [],
            tiles: [
                ...Array.from({ length: (i % 3) + 1 }, (_, k) => ({
                    ...insightTile,
                    name: `Insight ${k + 1}`,
                })),
                ...(i % 2 === 0 ? [textTile] : []),
            ],
        }
    }),
    ...Array.from(
        { length: 5 },
        (_, i): DashboardTemplateType => ({
            id: `tpl-official-featured-${i + 1}`,
            template_name: `Official featured starter ${i + 1}`,
            dashboard_description: 'Curated global template (thumb-up column + featured ordering).',
            scope: 'global',
            is_featured: true,
            tags:
                i === 0
                    ? ['product', 'onboarding', 'popular']
                    : i === 1
                      ? []
                      : i === 2
                        ? ['retention']
                        : i === 3
                          ? ['marketing', 'web', 'extras', 'more']
                          : ['engineering', 'sre'],
            dashboard_filters: {},
            variables: [],
            tiles: [
                { ...insightTile, name: 'Signups' },
                { ...insightTile, name: 'Retention' },
            ],
        })
    ),
    ...Array.from(
        { length: 15 },
        (_, i): DashboardTemplateType => ({
            id: `tpl-official-standard-${i + 1}`,
            template_name: `Official standard pack ${String(i + 1).padStart(2, '0')}`,
            dashboard_description: 'Non-featured official template in the global catalog.',
            scope: 'global',
            is_featured: false,
            tags:
                i % 4 === 0
                    ? []
                    : i % 4 === 1
                      ? ['baseline']
                      : i % 4 === 2
                        ? ['ops', 'incidents']
                        : ['lite', 'demo', 'tmp', 'scratch'],
            dashboard_filters: {},
            variables: [],
            tiles: i % 3 === 0 ? [insightTile, { ...insightTile, name: 'Funnel' }] : [insightTile],
        })
    ),
]

const tableListMocks = {
    get: {
        '/api/projects/:team_id/dashboard_templates/': toPaginatedResponse(sampleTemplates),
    },
}

/** Second project in the org so `eligibleDestinationTeamsCount` is non-zero and Copy appears in the row menu. */
const storySecondTeam: TeamType = {
    ...MOCK_DEFAULT_TEAM,
    id: 1002,
    name: 'Marketing site',
    uuid: '0178a3ab-story-0000-4b55-bceadebb0abc',
    project_id: 1002,
}

const storySecondProject: ProjectType = {
    id: storySecondTeam.id,
    name: storySecondTeam.name,
    organization_id: MOCK_ORGANIZATION_ID,
    created_at: MOCK_DEFAULT_PROJECT.created_at,
}

const organizationWithMultipleProjects: OrganizationType = {
    ...MOCK_DEFAULT_ORGANIZATION,
    teams: [MOCK_DEFAULT_TEAM, storySecondTeam],
    projects: [MOCK_DEFAULT_PROJECT, storySecondProject],
}

function organizationToUserOrganizationsList(
    organization: OrganizationType
): (typeof MOCK_DEFAULT_USER)['organizations'] {
    return [organization].map(
        ({
            id,
            name,
            slug,
            membership_level,
            members_can_use_personal_api_keys,
            allow_publicly_shared_resources,
            is_active,
            is_not_active_reason,
            is_pending_deletion,
        }) => ({
            id,
            name,
            slug,
            membership_level,
            members_can_use_personal_api_keys,
            allow_publicly_shared_resources,
            logo_media_id: null,
            is_active,
            is_not_active_reason,
            is_pending_deletion,
        })
    )
}

function storyUserForViewerMode(viewerMode: ViewerMode): UserType {
    return {
        ...MOCK_DEFAULT_USER,
        is_staff: viewerMode === 'staff',
        team: MOCK_DEFAULT_TEAM,
        organization: organizationWithMultipleProjects,
        organizations: organizationToUserOrganizationsList(organizationWithMultipleProjects),
    }
}

/** MSW follows `viewerMode` (Controls → Viewer mode). Always mock `@me` so `userLogic` loadUser does not overwrite the story org with a single-team user (staff mode previously had no handler). */
const withViewerModeMsw: Decorator = (Story, context) => {
    const viewerMode = ((context.args as { viewerMode?: ViewerMode }).viewerMode ?? 'staff') as ViewerMode
    const mocks = {
        get: {
            ...tableListMocks.get,
            '/api/users/@me/': (): [number, UserType] => [200, storyUserForViewerMode(viewerMode)],
        },
    }
    return mswDecorator(mocks)(Story, context)
}

function DashboardTemplatesTableStory({
    perspective,
    organization = organizationWithMultipleProjects,
}: {
    perspective: 'staff' | 'nonstaff'
    organization?: OrganizationType
}): JSX.Element {
    useEffect(() => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.CUSTOMER_DASHBOARD_TEMPLATE_AUTHORING], {
            [FEATURE_FLAGS.CUSTOMER_DASHBOARD_TEMPLATE_AUTHORING]: perspective === 'nonstaff',
        })
        userLogic.mount()
        // `userLogic` afterMount fires `loadUser()` while Kea resets MSW; that fetch often wins before this story's
        // `worker.use` override is registered, leaving `is_staff: true`. Hydrate explicitly so viewer mode matches UI.
        userLogic.actions.loadUserSuccess({
            ...MOCK_DEFAULT_USER,
            is_staff: perspective === 'staff',
            team: MOCK_DEFAULT_TEAM,
            organization,
            organizations: organizationToUserOrganizationsList(organization),
        })
        templatesTabListLogic.actions.getAllTemplates()
    }, [perspective, organization])
    return <DashboardTemplatesTable />
}

export const Default: Story = {
    args: {
        viewerMode: 'staff' satisfies ViewerMode,
    } as Record<string, unknown>,
    argTypes: {
        viewerMode: {
            control: 'inline-radio',
            options: ['staff', 'nonStaff'] satisfies ViewerMode[],
            description:
                'Org has two projects so team rows show Copy to another project. Staff: full staff menu. Non-staff: customer authoring + team-template actions.',
            name: 'Viewer mode',
        },
    },
    decorators: [withViewerModeMsw],
    render: (_, { args }) => {
        const viewerMode = ((args as { viewerMode?: ViewerMode }).viewerMode ?? 'staff') as ViewerMode
        return <DashboardTemplatesTableStory perspective={viewerMode === 'nonStaff' ? 'nonstaff' : 'staff'} />
    },
}
