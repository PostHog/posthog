import React, { useEffect } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'

import { Exporter } from './Exporter'
import { insight } from '~/exporter/Exporter.Insight.mocks'

export default {
    title: 'Exporter/Insight',
    component: Exporter,
    argTypes: {
        type: { defaultValue: 'embed' },
        insight: { defaultValue: insight },
        whitelabel: { defaultValue: false },
        noHeader: { defaultValue: false },
        legend: { defaultValue: false },
    },
    parameters: {
        docs: {
            inlineStories: false,
            source: { state: 'close' },
        },
    },
} as ComponentMeta<typeof Exporter>

export const Insight: ComponentStory<typeof Exporter> = (props) => {
    useEffect(() => {
        document.body.className = ''
        document.documentElement.className = `export-type-${props.type}`
    }, [])
    return (
        <div className={`storybook-export-type-${props.type}`}>
            <Exporter {...props} />
        </div>
    )
}
