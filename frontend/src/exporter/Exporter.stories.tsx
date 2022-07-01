import React, { useEffect } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { Exporter } from './Exporter'
import { insight } from '~/exporter/__mocks__/Exporter.mocks'

export default {
    title: 'Exporter/Insight',
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

export const InsightTrends = Template.bind({})
InsightTrends.args = { insight: insight }
