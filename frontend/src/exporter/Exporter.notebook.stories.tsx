import { useEffect } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { Exporter } from './Exporter'
import { notebook } from '~/exporter/__mocks__/Exporter.mocks'

export default {
    title: 'Exporter/Exporter',
    component: Exporter,
    args: {
        type: 'embed',
        whitelabel: false,
        noHeader: false,
        legend: false,
    },
    parameters: {
        docs: {
            inlineStories: false,
            iframeHeight: 400,
            source: { state: 'close' },
        },
        testOptions: {
            // KLUDGE: duplicated from Exporter.insight-and-dashboard.stories.tsx
            // so that we can set the correct waitForLoadersToDisappear
            waitForLoadersToDisappear: '[data-attr=notebook-loading-state]',
        },
        mockDate: '2023-02-01',
        viewMode: 'story',
    },
} as ComponentMeta<typeof Exporter>

const Template: ComponentStory<typeof Exporter> = (props) => {
    useEffect(() => {
        document.body.className = ''
        document.documentElement.className = `export-type-${props.type}`
    }, [props.type])
    return (
        <div className={`storybook-export-type-${props.type}`}>
            <Exporter {...props} />
        </div>
    )
}

export const Notebook = Template.bind({})
Notebook.args = { notebook }
