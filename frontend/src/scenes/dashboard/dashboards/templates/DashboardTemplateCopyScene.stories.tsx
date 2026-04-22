import { MOCK_DEFAULT_BASIC_USER, MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM, MOCK_TEAM_ID } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { InsightColor, type DashboardTemplateType, type OrganizationType, type TeamType } from '~/types'

import { DashboardTemplateCopyScene } from './DashboardTemplateCopyScene'

const SOURCE_TEMPLATE_ID = 'storybook-copy-source-template'

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

const mockSourceTemplate: DashboardTemplateType = {
    id: SOURCE_TEMPLATE_ID,
    template_name: 'Weekly KPIs (storybook)',
    dashboard_description: 'Team-scoped template shown on the copy-to-project scene.',
    scope: 'team',
    team_id: MOCK_TEAM_ID,
    created_by: MOCK_DEFAULT_BASIC_USER,
    tags: ['demo'],
    dashboard_filters: {},
    variables: [],
    tiles: [insightTile],
}

function teamClone(id: number, name: string, uuidSuffix: string): TeamType {
    return {
        ...MOCK_DEFAULT_TEAM,
        id,
        name,
        uuid: `0178a3ab-story-0000-4b55-bceadebb${uuidSuffix}`,
    }
}

const secondTeam = teamClone(1002, 'Marketing site', '0abc')
const thirdTeam = teamClone(1003, 'Beta environment', '0def')
const fourthTeam = teamClone(1004, 'Internal tools', '0ghi')

const organizationWithTwoProjects: OrganizationType = {
    ...MOCK_DEFAULT_ORGANIZATION,
    teams: [MOCK_DEFAULT_TEAM, secondTeam],
}

const organizationWithSeveralProjects: OrganizationType = {
    ...MOCK_DEFAULT_ORGANIZATION,
    teams: [MOCK_DEFAULT_TEAM, fourthTeam, secondTeam, thirdTeam],
}

const organizationWithSingleProject: OrganizationType = {
    ...MOCK_DEFAULT_ORGANIZATION,
    teams: [MOCK_DEFAULT_TEAM],
}

const templateDetailPath = `/api/projects/:team_id/dashboard_templates/${SOURCE_TEMPLATE_ID}/`

const copyBetweenProjectsPath = '/api/projects/:team_id/dashboard_templates/copy_between_projects/'

const baseMocks = {
    get: {
        '/api/organizations/@current/': (): [number, OrganizationType] => [200, organizationWithTwoProjects],
        [templateDetailPath]: (): [number, DashboardTemplateType] => [200, mockSourceTemplate],
    },
    post: {
        [copyBetweenProjectsPath]: (): [number, DashboardTemplateType] => [
            201,
            {
                ...mockSourceTemplate,
                id: 'storybook-copied-template',
                team_id: secondTeam.id,
                template_name: `${mockSourceTemplate.template_name} (copy)`,
            },
        ],
    },
}

function WithOrganizationForStory({
    organization,
    children,
}: {
    organization: OrganizationType
    children: React.ReactNode
}): JSX.Element {
    useEffect(() => {
        organizationLogic.mount()
        organizationLogic.actions.loadCurrentOrganizationSuccess(organization)
    }, [organization])
    return <>{children}</>
}

const meta: Meta<typeof DashboardTemplateCopyScene> = {
    title: 'Scenes-App/Dashboards/Templates/Dashboard template copy',
    component: DashboardTemplateCopyScene,
    decorators: [
        mswDecorator(baseMocks),
        (Story) => (
            <div className="bg-primary min-h-screen w-full p-4">
                <Story />
            </div>
        ),
    ],
    args: {
        sourceTemplateId: SOURCE_TEMPLATE_ID,
        sourceTeamId: MOCK_TEAM_ID,
    },
    parameters: {
        posthogTheme: 'light',
        backgrounds: { default: 'light' },
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: urls.dashboardTemplateCopyToProject(SOURCE_TEMPLATE_ID, MOCK_TEAM_ID),
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
}

export default meta

type Story = StoryObj<typeof DashboardTemplateCopyScene>

export const Default: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/organizations/@current/': (): [number, OrganizationType] => [
                    200,
                    organizationWithSeveralProjects,
                ],
                [templateDetailPath]: [200, mockSourceTemplate],
            },
            post: {
                [copyBetweenProjectsPath]: (): [number, DashboardTemplateType] => [
                    201,
                    {
                        ...mockSourceTemplate,
                        id: 'storybook-copied-template',
                        team_id: secondTeam.id,
                        template_name: `${mockSourceTemplate.template_name} (copy)`,
                    },
                ],
            },
        }),
    ],
    render: (args) => (
        <WithOrganizationForStory organization={organizationWithSeveralProjects}>
            <DashboardTemplateCopyScene {...args} />
        </WithOrganizationForStory>
    ),
}

export const LoadError: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/organizations/@current/': (): [number, OrganizationType] => [200, organizationWithTwoProjects],
                [templateDetailPath]: (): [number] => [404],
            },
        }),
    ],
    render: (args) => (
        <WithOrganizationForStory organization={organizationWithTwoProjects}>
            <DashboardTemplateCopyScene {...args} />
        </WithOrganizationForStory>
    ),
}

export const NoOtherProjectsInOrganization: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/organizations/@current/': (): [number, OrganizationType] => [200, organizationWithSingleProject],
                [templateDetailPath]: [200, mockSourceTemplate],
            },
        }),
    ],
    render: (args) => (
        <WithOrganizationForStory organization={organizationWithSingleProject}>
            <DashboardTemplateCopyScene {...args} />
        </WithOrganizationForStory>
    ),
}
