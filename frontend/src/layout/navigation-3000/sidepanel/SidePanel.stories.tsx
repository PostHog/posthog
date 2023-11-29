import { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { router } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { setFeatureFlags } from '~/mocks/browser'
import { SidePanelTab } from '~/types'

import { sidePanelStateLogic } from './sidePanelStateLogic'

const meta: Meta = {
    title: 'Scenes-App/SidePanels',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-07-04', // To stabilize relative dates
    },
}
export default meta

const BaseTemplate = (props: { panel: SidePanelTab }): JSX.Element => {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    setFeatureFlags([FEATURE_FLAGS.POSTHOG_3000])
    useEffect(() => {
        router.actions.push(urls.dashboards())
        openSidePanel(props.panel)
    }, [])

    return <App />
}

export const SidePanelDocs: StoryFn = () => {
    return <BaseTemplate panel={SidePanelTab.Docs} />
}

export const SidePanelSettings: StoryFn = () => {
    return <BaseTemplate panel={SidePanelTab.Settings} />
}

export const SidePanelActivation: StoryFn = () => {
    return <BaseTemplate panel={SidePanelTab.Activation} />
}

export const SidePanelNotebooks: StoryFn = () => {
    return <BaseTemplate panel={SidePanelTab.Notebooks} />
}
