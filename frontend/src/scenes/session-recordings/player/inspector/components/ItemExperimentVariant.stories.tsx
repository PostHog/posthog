import type { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'
import {
    ItemExperimentVariant,
    ItemExperimentVariantDetail,
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

const makeExperimentVariantItem = (
    experimentName: string,
    variant: string,
    variantsSeen: string[] = [variant]
): InspectorListItemExperimentVariant => {
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
            multipleVariants: variantsSeen.length > 1,
            variantsSeen,
        },
        key: 'experiment-variant-101',
    }
}

const renderDetail = (props: ItemExperimentVariantProps): JSX.Element => (
    <div className="flex flex-col gap-2 min-w-96 max-w-160">
        <ItemExperimentVariantDetail {...props} />
    </div>
)

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

export const Detail: Story = {
    args: {
        item: makeExperimentVariantItem('Checkout CTA copy', 'test'),
    },
    render: renderDetail,
}

export const DetailMultipleVariants: Story = {
    args: {
        item: makeExperimentVariantItem('Checkout CTA copy', 'test', ['control', 'test']),
    },
    render: renderDetail,
}
