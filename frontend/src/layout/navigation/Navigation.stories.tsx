import { Meta } from '@storybook/react'
import { TopBar } from './TopBar/TopBar'
import { SideBar } from './SideBar/SideBar'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton, LemonTable } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { navigationLogic } from './navigationLogic'
import { useEffect } from 'react'

export default {
    title: 'Layout/Navigation',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        viewMode: 'story',
        testRunner: { includeNavigation: true },
    },
} as Meta

function BaseAppPage(): JSX.Element {
    return (
        <>
            <TopBar />
            <SideBar>
                <div className="main-app-content">
                    <PageHeader
                        title="Your gizmos"
                        caption="View your household devices."
                        buttons={<LemonButton type="primary">New gizmo</LemonButton>}
                    />
                    <LemonTable
                        columns={[
                            { title: 'Name', dataIndex: 'name' },
                            { title: 'Function', dataIndex: 'function' },
                            { title: 'Color', dataIndex: 'color' },
                            { title: 'Ionization level', dataIndex: 'ionizationLevel' },
                        ]}
                        dataSource={[
                            // Nonsensical data for demo purposes
                            {
                                name: 'Blargifier',
                                function: 'Radicalizes blue whales',
                                color: 'Azure',
                                ionizationLevel: 423,
                            },
                            {
                                name: 'Frink',
                                function: 'Makes the world go round',
                                color: 'Crimson',
                                ionizationLevel: 0,
                            },
                            {
                                name: 'Torpurator',
                                function: 'Spontaneously combusts',
                                color: 'Chartreuse',
                                ionizationLevel: 100,
                            },
                            {
                                name: 'De-Blargifier',
                                function: 'De-radicalizes blue whales',
                                color: 'Beige',
                                ionizationLevel: -423,
                            },
                        ]}
                    />
                </div>
            </SideBar>
        </>
    )
}

export function AppPageWithSideBarHidden(): JSX.Element {
    const { toggleSideBarBase, toggleSideBarMobile } = useActions(navigationLogic)

    useEffect(() => {
        toggleSideBarBase(false)
        toggleSideBarMobile(false)
    }, [])

    return <BaseAppPage />
}

export function AppPageWithSideBarShown(): JSX.Element {
    const { toggleSideBarBase, toggleSideBarMobile } = useActions(navigationLogic)

    useEffect(() => {
        toggleSideBarBase(true)
        toggleSideBarMobile(true)
    }, [])

    return <BaseAppPage />
}
