import { ComponentMeta, ComponentStory } from '@storybook/react'
import { PostHogQuery, PostHogQueryProps } from '~/queries/PostHogQuery'
import { LegacyQuery, NodeCategory, NodeType } from '~/queries/nodes'
import { InsightType } from '~/types'

export default {
    title: 'Components/PostHogQuery',
    component: PostHogQuery,
    parameters: { chromatic: { disableSnapshot: false } },
    argTypes: {
        query: { defaultValue: {} },
    },
} as ComponentMeta<typeof PostHogQuery>

const BasicTemplate: ComponentStory<typeof PostHogQuery> = (props: PostHogQueryProps) => {
    return <PostHogQuery {...props} />
}

export const LegacyInsight = BasicTemplate.bind({})
const legacyInsight: LegacyQuery = {
    nodeType: NodeType.LegacyQuery,
    nodeCategory: NodeCategory.DataNode,
    filters: { insight: InsightType.TRENDS },
}
LegacyInsight.args = {
    query: legacyInsight,
}
