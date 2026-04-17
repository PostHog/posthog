import { MOCK_DEFAULT_BASIC_USER, MOCK_DEFAULT_USER, MOCK_TEAM_ID } from 'lib/api.mock'

import { Meta, StoryObj, type Decorator } from '@storybook/react'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DashboardTemplateEditor } from 'scenes/dashboard/DashboardTemplateEditor'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'
import { InsightColor, type DashboardTemplateType } from '~/types'

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

const nonStaffUserMocks = {
    get: {
        '/api/users/@me/': (): [number, typeof MOCK_DEFAULT_USER] => [200, { ...MOCK_DEFAULT_USER, is_staff: false }],
    },
}

/** MSW follows `viewerMode` (Controls → Viewer mode). */
const withViewerModeMsw: Decorator = (Story, context) => {
    const viewerMode = ((context.args as { viewerMode?: ViewerMode }).viewerMode ?? 'staff') as ViewerMode
    const mocks = {
        get: {
            ...tableListMocks.get,
            ...(viewerMode === 'nonStaff' ? nonStaffUserMocks.get : {}),
        },
    }
    return mswDecorator(mocks)(Story, context)
}

function DashboardTemplatesTableStory({ perspective }: { perspective: 'staff' | 'nonstaff' }): JSX.Element {
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
        })
        templatesTabListLogic.actions.getAllTemplates()
    }, [perspective])
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
                'Staff: Monaco + scope + delete rules on rows. Non-staff: customer authoring + Edit/Delete on team templates only.',
            name: 'Viewer mode',
        },
    },
    decorators: [withViewerModeMsw],
    render: (_, { args }) => {
        const viewerMode = ((args as { viewerMode?: ViewerMode }).viewerMode ?? 'staff') as ViewerMode
        return <DashboardTemplatesTableStory perspective={viewerMode === 'nonStaff' ? 'nonstaff' : 'staff'} />
    },
}
