import { MOCK_DEFAULT_USER, MOCK_TEAM_ID } from 'lib/api.mock'

import { Meta, StoryObj, type Decorator } from '@storybook/react'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DashboardTemplateEditor } from 'scenes/dashboard/DashboardTemplateEditor'
import { dashboardTemplateEditorLogic } from 'scenes/dashboard/dashboardTemplateEditorLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { mswDecorator } from '~/mocks/browser'
import type { DashboardTemplateEditorType, DashboardTemplateType } from '~/types'

import { DashboardTemplateModal } from './DashboardTemplateModal'
import { dashboardTemplateModalLogic } from './dashboardTemplateModalLogic'

type ViewerMode = 'staff' | 'nonStaff'

type ModalStoryVariant = 'create' | 'edit'

const templateMocks = {
    get: {
        '/api/projects/:team_id/dashboard_templates/': require('../../__mocks__/dashboard_templates.json'),
        '/api/projects/:team_id/dashboard_templates/json_schema/': require('../../__mocks__/dashboard_template_schema.json'),
    },
}

const nonStaffUserMocks = {
    get: {
        '/api/users/@me/': (): [number, typeof MOCK_DEFAULT_USER] => [200, { ...MOCK_DEFAULT_USER, is_staff: false }],
    },
}

const withViewerModeMsw: Decorator = (Story, context) => {
    const viewerMode = ((context.args as { viewerMode?: ViewerMode }).viewerMode ?? 'nonStaff') as ViewerMode
    return mswDecorator({
        get: {
            ...templateMocks.get,
            ...(viewerMode === 'nonStaff' ? nonStaffUserMocks.get : {}),
        },
    })(Story, context)
}

const meta = {
    title: 'Scenes-App/Dashboards/Templates/DashboardTemplateModal',
    decorators: [
        (Story) => (
            <div className="bg-primary min-h-screen w-full p-4">
                <Story />
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
    argTypes: {
        viewerMode: {
            control: 'inline-radio',
            options: ['staff', 'nonStaff'] satisfies ViewerMode[],
            description:
                'Non-staff + authoring flag: customer save-as-template. Staff: optional full JSON from the project modal on create and edit; Monaco story below.',
            name: 'Viewer mode',
        },
    },
} satisfies Meta

export default meta

type ModalStory = StoryObj<typeof DashboardTemplateModal>

const sampleCreatePayload: DashboardTemplateEditorType = {
    template_name: '',
    dashboard_description: '',
    dashboard_filters: {},
    tags: [],
    tiles: [
        {
            name: 'Example',
            type: 'INSIGHT',
            color: 'blue',
            layouts: {},
            filters: {},
        },
    ],
}

const sampleEditingTemplate: DashboardTemplateType = {
    id: 'tpl-story-edit',
    template_name: 'Weekly KPIs',
    dashboard_description: 'Project template open for edit (metadata only in this modal).',
    scope: 'team',
    team_id: MOCK_TEAM_ID,
    tags: ['kpi', 'growth'],
    dashboard_filters: {},
    tiles: [
        {
            name: 'Example',
            type: 'INSIGHT',
            color: 'blue',
            layouts: {},
            filters: {},
        },
    ],
}

function DashboardTemplateModalStory({
    viewerMode,
    variant,
}: {
    viewerMode: ViewerMode
    variant: ModalStoryVariant
}): JSX.Element {
    useEffect(() => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.CUSTOMER_DASHBOARD_TEMPLATE_AUTHORING], {
            [FEATURE_FLAGS.CUSTOMER_DASHBOARD_TEMPLATE_AUTHORING]: viewerMode === 'nonStaff',
        })
        userLogic.mount()
        userLogic.actions.loadUser()
        dashboardTemplateModalLogic.mount()
        if (variant === 'create') {
            dashboardTemplateModalLogic.actions.openCreate(sampleCreatePayload)
        } else {
            dashboardTemplateModalLogic.actions.openEdit(sampleEditingTemplate)
        }
    }, [viewerMode, variant])

    return <DashboardTemplateModal />
}

function renderModalStory(variant: ModalStoryVariant) {
    return (_: unknown, { args }: { args: Record<string, unknown> }): JSX.Element => {
        const viewerMode = ((args as { viewerMode?: ViewerMode }).viewerMode ?? 'nonStaff') as ViewerMode
        return <DashboardTemplateModalStory viewerMode={viewerMode} variant={variant} />
    }
}

export const Create: ModalStory = {
    args: {
        viewerMode: 'nonStaff' satisfies ViewerMode,
    } as Record<string, unknown>,
    decorators: [withViewerModeMsw],
    render: renderModalStory('create'),
}

export const Edit: ModalStory = {
    args: {
        viewerMode: 'nonStaff' satisfies ViewerMode,
    } as Record<string, unknown>,
    decorators: [withViewerModeMsw],
    render: renderModalStory('edit'),
}

function DashboardTemplateEditorStory({ viewerMode }: { viewerMode: ViewerMode }): JSX.Element {
    useEffect(() => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.CUSTOMER_DASHBOARD_TEMPLATE_AUTHORING], {
            [FEATURE_FLAGS.CUSTOMER_DASHBOARD_TEMPLATE_AUTHORING]: viewerMode === 'nonStaff',
        })
        userLogic.mount()
        userLogic.actions.loadUser()
        dashboardTemplateEditorLogic.mount()
        dashboardTemplateEditorLogic.actions.clear()
        dashboardTemplateEditorLogic.actions.openDashboardTemplateEditor()
        dashboardTemplateEditorLogic.actions.setEditorValue(
            JSON.stringify(
                {
                    id: '123',
                    template_name: 'My Template',
                },
                null,
                4
            )
        )
    }, [viewerMode])

    return <DashboardTemplateEditor inline={true} />
}

const withViewerModeMswEditorDefaultStaff: Decorator = (Story, context) => {
    const viewerMode = ((context.args as { viewerMode?: ViewerMode }).viewerMode ?? 'staff') as ViewerMode
    return mswDecorator({
        get: {
            ...templateMocks.get,
            ...(viewerMode === 'nonStaff' ? nonStaffUserMocks.get : {}),
        },
    })(Story, context)
}

export const FullJsonEditor: StoryObj<typeof DashboardTemplateEditor> = {
    args: {
        viewerMode: 'staff' satisfies ViewerMode,
    } as Record<string, unknown>,
    argTypes: {
        viewerMode: {
            control: 'inline-radio',
            options: ['staff', 'nonStaff'] satisfies ViewerMode[],
            description:
                'Staff: Monaco JSON editor as opened from dashboard flows. Non-staff: same shell in Storybook for comparison.',
            name: 'Viewer mode',
        },
    },
    decorators: [withViewerModeMswEditorDefaultStaff],
    render: (_, { args }) => {
        const viewerMode = ((args as { viewerMode?: ViewerMode }).viewerMode ?? 'staff') as ViewerMode
        return <DashboardTemplateEditorStory viewerMode={viewerMode} />
    },
}
