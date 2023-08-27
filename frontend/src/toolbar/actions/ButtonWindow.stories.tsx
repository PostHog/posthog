import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useStorybookMocks } from '~/mocks/browser'
import { useToolbarStyles } from '~/toolbar/Toolbar.stories'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { ActionsTab } from '~/toolbar/actions/ActionsTab'
import { ButtonWindow } from '~/toolbar/button/ButtonWindow'
import { FeatureFlags } from '~/toolbar/flags/FeatureFlags'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { featureFlagsLogic } from '~/toolbar/flags/featureFlagsLogic'
interface StoryProps {
    contents: JSX.Element
    name: string
    label: string
    tagComponent?: JSX.Element
}
type Story = StoryObj<(props: StoryProps) => JSX.Element>
const meta: Meta<(props: StoryProps) => JSX.Element> = {
    title: 'Scenes-Other/Toolbar/Components',
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
            ],
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
    useMountedLogic(actionsTabLogic)
    const theMountedHeatmapLoggic = useMountedLogic(heatmapLogic)
    if (props.name === 'heatmap') {
        theMountedHeatmapLoggic.actions.getElementStats()
    }
    useMountedLogic(featureFlagsLogic)

    useToolbarStyles()

    return (
        <div className="">
            <ButtonWindow
                name={props.name}
                label={props.label}
                tagComponent={props.tagComponent}
                visible={true}
                close={() => {}}
                position={{ x: 0, y: 0 }}
                savePosition={() => {}}
            >
                {props.contents}
            </ButtonWindow>
        </div>
    )
}

export const Actions: Story = Template.bind({})
Actions.args = { contents: <ActionsTab />, name: 'actions', label: 'Actions' }

// TODO the heatmap window processes the DOM of the page so will need a bunch of extra setup 🙈

export const Flags: Story = Template.bind({})
Flags.args = {
    contents: <FeatureFlags />,
    name: 'flags',
    label: 'Feature Flags',
    tagComponent: <span className="overridden-tag">1 overridden</span>,
}
