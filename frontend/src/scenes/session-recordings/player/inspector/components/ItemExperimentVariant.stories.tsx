import type { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'
import {
    ItemExperimentVariant,
    ItemExperimentVariantProps,
} from 'scenes/session-recordings/player/inspector/components/ItemExperimentVariant'
import { InspectorListItemExperimentVariant } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

type Story = StoryObj<ItemExperimentVariantProps>
const meta: Meta<ItemExperimentVariantProps> = {
    title: 'Components/PlayerInspector/ItemExperimentVariant',
    component: ItemExperimentVariant,
    render: (props) => {
        return (
            <div className="flex flex-col gap-2 min-w-96 max-w-160">
                <ItemExperimentVariant {...props} />
            </div>
        )
    },
}
export default meta

const makeExperimentVariantItem = (experimentName: string, variant: string): InspectorListItemExperimentVariant => {
    return {
        type: 'experiment-variant',
        timestamp: dayjs('2023-05-01T14:46:24Z'),
        timeInRecording: 4000,
        search: `experiment variant ${experimentName} ${variant}`,
        data: {
            id: 'experiment-variant-101',
            experimentId: 101,
            experimentName,
            flagKey: 'checkout-cta',
            variant,
        },
        key: 'experiment-variant-101',
    }
}

export const Default: Story = {
    args: {
        item: makeExperimentVariantItem('Checkout CTA copy', 'test'),
    },
}

export const LongExperimentName: Story = {
    args: {
        item: makeExperimentVariantItem(
            'An exceedingly long experiment name that should wrap rather than blow out the inspector row layout',
            'control-with-a-long-variant-key'
        ),
    },
}
