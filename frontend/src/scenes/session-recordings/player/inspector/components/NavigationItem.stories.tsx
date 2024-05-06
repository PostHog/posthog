import { Meta, StoryFn, StoryObj } from '@storybook/react'
import {
    NavigationItem,
    NavigationItemProps,
} from 'scenes/session-recordings/player/inspector/components/NavigationItem'
import { NetworkRequestTiming } from 'scenes/session-recordings/player/inspector/components/Timing/NetworkRequestTiming'

import { mswDecorator } from '~/mocks/browser'
import { PerformanceEvent } from '~/types'

type Story = StoryObj<typeof NavigationItem>
const meta: Meta<typeof NetworkRequestTiming> = {
    title: 'Components/NetworkRequest/NavigationItem',
    component: NetworkRequestTiming,
    decorators: [
        mswDecorator({
            get: {},
        }),
    ],
}
export default meta

/**
 * loads the following into performance cards
 * first_contentful_paint
 * dom_interactive
 * load_event_end
 * @constructor
 */
const BasicTemplate: StoryFn<typeof NavigationItem> = (props: Partial<NavigationItemProps>) => {
    return (
        <NavigationItem
            navigationURL={props.navigationURL || 'http://localhost:8000/insights'}
            expanded={props.expanded === undefined ? true : props.expanded}
            item={
                props.item ||
                ({
                    // fake an event with every card visible
                    load_event_end: 90,
                    dom_interactive: 70,
                    first_contentful_paint: 10,
                } as PerformanceEvent)
            }
        />
    )
}

export const Default: Story = BasicTemplate.bind({})
Default.args = {}

/**
 * FCP benchmarks are scoreBenchmarks: [1800, 3000],
 */
export const SlowFCP: Story = BasicTemplate.bind({})
SlowFCP.args = {
    item: {
        load_event_end: 90,
        dom_interactive: 70,
        first_contentful_paint: 1900,
    } as PerformanceEvent,
    expanded: false,
}

export const ReallySlowFCP: Story = BasicTemplate.bind({})
ReallySlowFCP.args = {
    item: {
        load_event_end: 90,
        dom_interactive: 70,
        first_contentful_paint: 3100,
    } as PerformanceEvent,
    expanded: false,
}

/**
 * DOM interactive benchmarks are [3800, 7300],
 */
export const SlowDOMInteractive: Story = BasicTemplate.bind({})
SlowDOMInteractive.args = {
    item: {
        load_event_end: 90,
        dom_interactive: 3900,
        first_contentful_paint: 10,
    } as PerformanceEvent,
    expanded: false,
}

export const ReallySlowDOMInteractive: Story = BasicTemplate.bind({})
ReallySlowDOMInteractive.args = {
    item: {
        load_event_end: 90,
        dom_interactive: 7400,
        first_contentful_paint: 10,
    } as PerformanceEvent,
    expanded: false,
}

/**
 * Load event benchmarks are [3800, 7300],
 */
export const SlowLoadEvent: Story = BasicTemplate.bind({})
SlowLoadEvent.args = {
    item: {
        load_event_end: 3900,
        dom_interactive: 70,
        first_contentful_paint: 10,
    } as PerformanceEvent,
    expanded: false,
}

export const ReallySlowLoadEvent: Story = BasicTemplate.bind({})
ReallySlowLoadEvent.args = {
    item: {
        load_event_end: 7400,
        dom_interactive: 70,
        first_contentful_paint: 10,
    } as PerformanceEvent,
    expanded: false,
}

export const AllSlow: Story = BasicTemplate.bind({})
AllSlow.args = {
    item: {
        load_event_end: 7400,
        dom_interactive: 7400,
        first_contentful_paint: 3100,
    } as PerformanceEvent,
    expanded: false,
}

export const Expanded: Story = BasicTemplate.bind({})
Expanded.args = {
    expanded: true,
}
