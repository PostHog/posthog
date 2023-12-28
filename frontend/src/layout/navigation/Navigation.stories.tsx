import { LemonButton, LemonTable } from '@posthog/lemon-ui'
import { Meta } from '@storybook/react'
import { PageHeader } from 'lib/components/PageHeader'

import { SideBar } from './SideBar/SideBar'

const meta: Meta = {
    title: 'Layout/Navigation',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta
function BaseAppPage(): JSX.Element {
    return (
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
    )
}

export function AppPageWithSideBarHidden(): JSX.Element {
    return <BaseAppPage />
}

export function AppPageWithSideBarShown(): JSX.Element {
    return <BaseAppPage />
}
