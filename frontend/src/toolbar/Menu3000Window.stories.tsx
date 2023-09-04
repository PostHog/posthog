import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useStorybookMocks } from '~/mocks/browser'
import { useToolbarStyles } from '~/toolbar/Toolbar.stories'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { ActionsTab } from '~/toolbar/actions/ActionsTab'
import { FeatureFlags } from '~/toolbar/flags/FeatureFlags'
import { featureFlagsLogic } from '~/toolbar/flags/featureFlagsLogic'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import clsx from 'clsx'

const listActionsAPIResponse = {
    results: [
        {
            id: 49103,
            name: 'Clicked notification row',
            description: '',
            post_to_slack: false,
            slack_message_format: '',
            steps: [
                {
                    id: '60889',
                    event: '$autocapture',
                    tag_name: null,
                    text: null,
                    text_matching: null,
                    href: null,
                    href_matching: null,
                    selector: '.notifications-menu .activity-log-row',
                    url: null,
                    name: null,
                    url_matching: 'contains',
                    properties: [],
                },
            ],
            created_at: '2023-08-22T06:31:40.495488Z',
            created_by: {
                id: 5042,
                uuid: '017bcbcf-2391-0000-1868-14fb987285c5',
                distinct_id: 'PqMBBFBfKo638PwvjCWTSZ6dnswYzJ3RtH8VIHCBWAy',
                first_name: 'Paul',
                email: 'paul@posthog.com',
                is_email_verified: true,
            },
            deleted: false,
            is_calculating: false,
            last_calculated_at: '2023-08-22T06:31:40.495197Z',
            team_id: 2,
            is_action: true,
            bytecode_error: null,
            tags: [],
        },
        {
            id: 49059,
            name: 'clicked nav bar2',
            description: '',
            post_to_slack: false,
            slack_message_format: '',
            steps: [
                {
                    id: '60829',
                    event: '$autocapture',
                    tag_name: null,
                    text: 'Products',
                    text_matching: null,
                    href: '/product-analytics',
                    href_matching: null,
                    selector: null,
                    url: null,
                    name: '',
                    url_matching: 'exact',
                    properties: [],
                },
                {
                    id: '60830',
                    event: '$autocapture',
                    tag_name: null,
                    text: null,
                    text_matching: null,
                    href: null,
                    href_matching: null,
                    selector: '.border-b .h-full:nth-child(2) > .text-\\[13\\.5px\\]',
                    url: null,
                    name: '',
                    url_matching: 'exact',
                    properties: [],
                },
            ],
            created_at: '2023-08-21T20:54:17.218311Z',
            created_by: {
                id: 6352,
                uuid: '017d5334-911a-0000-6954-2d394263f3ca',
                distinct_id: '48vHN2rW28SvzA6D4NdgHajLOjBP1ulsI0Rr5DNas4i',
                first_name: 'Cameron',
                email: 'cameron@posthog.com',
                is_email_verified: true,
            },
            deleted: false,
            is_calculating: false,
            last_calculated_at: '2023-08-21T20:54:17.218023Z',
            team_id: 2,
            is_action: true,
            bytecode_error: null,
            tags: [],
        },
        {
            id: 49050,
            name: 'Clicked Products in nav bar',
            description: '',
            post_to_slack: false,
            slack_message_format: '',
            steps: [
                {
                    id: '60819',
                    event: '$autocapture',
                    tag_name: null,
                    text: 'Products',
                    text_matching: null,
                    href: '/product-analytics',
                    href_matching: null,
                    selector: null,
                    url: null,
                    name: '',
                    url_matching: 'exact',
                    properties: [],
                },
                {
                    id: '60820',
                    event: '$autocapture',
                    tag_name: null,
                    text: 'Pricing',
                    text_matching: null,
                    href: '/pricing',
                    href_matching: null,
                    selector: null,
                    url: null,
                    name: null,
                    url_matching: 'contains',
                    properties: [],
                },
            ],
            created_at: '2023-08-21T18:46:13.210958Z',
            created_by: {
                id: 6352,
                uuid: '017d5334-911a-0000-6954-2d394263f3ca',
                distinct_id: '48vHN2rW28SvzA6D4NdgHajLOjBP1ulsI0Rr5DNas4i',
                first_name: 'Cameron',
                email: 'cameron@posthog.com',
                is_email_verified: true,
            },
            deleted: false,
            is_calculating: false,
            last_calculated_at: '2023-08-21T18:46:13.210590Z',
            team_id: 2,
            is_action: true,
            bytecode_error: null,
            tags: [],
        },
    ],
}

interface StoryProps {
    contents: JSX.Element
    name: string
    label: string
    tagComponent?: JSX.Element
    listActionsAPIResponse?: { results: any[] }
    theme: 'light' | 'dark' | null
}

type Story = StoryObj<(props: StoryProps) => JSX.Element>
const meta: Meta<(props: StoryProps) => JSX.Element> = {
    title: 'Scenes-Other/Toolbar/Components/3000',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta

const Template: StoryFn<StoryProps> = (props: StoryProps) => {
    useStorybookMocks({
        get: {
            '/decide': {
                config: {
                    enable_collect_everything: true,
                },
                toolbarParams: {
                    toolbarVersion: 'toolbar',
                    jsURL: 'http://localhost:8234/',
                },
                isAuthenticated: true,
                supportedCompression: ['gzip', 'gzip-js', 'lz64'],
                featureFlags: {},
                sessionRecording: {
                    endpoint: '/s/',
                },
            },
            '/api/element/stats/': {
                results: [{ count: 1592 }, { count: 12 }],
            },
            '/api/projects/@current/feature_flags/my_flags': [
                {
                    feature_flag: {
                        id: 15927,
                        name: 'Example flag',
                        key: 'example-one',
                        deleted: false,
                        active: true,
                        created_at: '2023-08-17T19:37:05.259538Z',
                        filters: {},
                    },
                    value: false,
                },
                {
                    feature_flag: {
                        id: 15927,
                        name: 'Another example flag',
                        key: 'example-two',
                        deleted: false,
                        active: true,
                        created_at: '2023-08-17T19:37:05.259538Z',
                        filters: {},
                    },
                    value: true,
                },
                {
                    feature_flag: {
                        id: 13859,
                        name: 'Example multivariate flag',
                        key: 'my-multi-example',
                        filters: {
                            multivariate: {
                                variants: [
                                    {
                                        key: 'control',
                                        rollout_percentage: 50,
                                    },
                                    {
                                        key: 'test',
                                        rollout_percentage: 50,
                                    },
                                ],
                            },
                        },
                        deleted: false,
                        active: true,
                    },
                    value: 'control',
                },
                {
                    feature_flag: {
                        id: 13859,
                        name: 'Example overridden multivariate flag',
                        key: 'my-other-multi-example',
                        filters: {
                            multivariate: {
                                variants: [
                                    {
                                        key: 'control',
                                        rollout_percentage: 50,
                                    },
                                    {
                                        key: 'test',
                                        rollout_percentage: 50,
                                    },
                                ],
                            },
                        },
                        deleted: false,
                        active: true,
                    },
                    value: 'control',
                },
            ],
            '/api/projects/@current/actions/': props.listActionsAPIResponse || { results: [] },
        },
    })

    const toolbarParams = {
        temporaryToken: 'UExb1dCsoqBtrhrZYxzmxXQ7XdjVH5Ea_zbQjTFuJqk',
        actionId: undefined,
        userIntent: undefined,
        dataAttributes: ['data-attr'],
        apiURL: '/',
        jsURL: 'http://localhost:8234/',
        userEmail: 'foobar@posthog.com',
    }
    useMountedLogic(toolbarLogic(toolbarParams))
    const theMountedActionsLogic = useMountedLogic(actionsLogic)
    if (props.name === 'actions') {
        theMountedActionsLogic.actions.getActions()
    }
    useMountedLogic(actionsTabLogic)

    const theMountedFlagsLogic = useMountedLogic(featureFlagsLogic)
    if (props.name === 'flags') {
        theMountedFlagsLogic.actions.storeLocalOverrides({ 'example-two': false, 'my-other-multi-example': 'test' })
    }

    useToolbarStyles()

    const themeProps = props.theme ? { theme: props.theme } : {}

    return (
        <div
            id={'button-toolbar'}
            className={clsx('flex flex-row gap-4', props.theme ? 'posthog-3000 Toolbar3000' : '')}
            {...themeProps}
            key={props.theme ? props.theme : 'no-theme'}
            /* eslint-disable-next-line react/forbid-dom-props */
            style={{ width: 310, height: 400 }}
        >
            <h5>{props.label}</h5>
            {props.contents}
        </div>
    )
}

export const Actions: Story = Template.bind({})
Actions.args = { contents: <ActionsTab />, name: 'actions', label: 'Actions' }

export const ActionsLightMode: Story = Template.bind({})
ActionsLightMode.args = { contents: <ActionsTab />, name: 'actions', label: 'Actions (light mode)', theme: 'light' }

export const ActionsDarkMode: Story = Template.bind({})
ActionsDarkMode.args = { contents: <ActionsTab />, name: 'actions', label: 'Actions (dark mode)', theme: 'dark' }

export const ActionsWithResults: Story = Template.bind({})
ActionsWithResults.args = {
    contents: <ActionsTab />,
    name: 'actions',
    label: 'Actions',
    listActionsAPIResponse: listActionsAPIResponse,
}

export const ActionsWithResultsLightMode: Story = Template.bind({})
ActionsWithResultsLightMode.args = {
    contents: <ActionsTab />,
    name: 'actions',
    label: 'Actions',
    listActionsAPIResponse: listActionsAPIResponse,
    theme: 'light',
}

export const ActionsWithResultsDarkMode: Story = Template.bind({})
ActionsWithResultsDarkMode.args = {
    contents: <ActionsTab />,
    name: 'actions',
    label: 'Actions',
    listActionsAPIResponse: listActionsAPIResponse,
    theme: 'dark',
}

// TODO the heatmap window processes the DOM of the page so will need a bunch of extra setup 🙈

export const Flags: Story = Template.bind({})
Flags.args = {
    contents: <FeatureFlags />,
    name: 'flags',
    label: 'Feature Flags',
    tagComponent: <span className="overridden-tag">1 overridden</span>,
}

export const FlagsLightMode: Story = Template.bind({})
FlagsLightMode.args = {
    contents: <FeatureFlags />,
    name: 'flags',
    label: 'Feature Flags',
    tagComponent: <span className="overridden-tag">1 overridden</span>,
    theme: 'light',
}

export const FlagsDarkMode: Story = Template.bind({})
FlagsDarkMode.args = {
    contents: <FeatureFlags />,
    name: 'flags',
    label: 'Feature Flags',
    tagComponent: <span className="overridden-tag">1 overridden</span>,
    theme: 'dark',
}
