import type { Meta, StoryObj } from '@storybook/react'

import { detailItems, offlineDetailItemResults } from './offlineDetailFixtures'
import { OfflineResultTag } from './OfflineResultTag'

const result = offlineDetailItemResults(detailItems[0].id)[0]
const meta: Meta<typeof OfflineResultTag> = {
    title: 'AI observability/Offline experiments/Result tag',
    component: OfflineResultTag,
    parameters: { layout: 'padded' },
    args: { result, scorer: result.scorer },
}
export default meta
type Story = StoryObj<typeof OfflineResultTag>

export const NumericFailure: Story = {}
export const NumericPass: Story = { args: { result: { ...result, value: 0.9 } } }
export const BooleanDetector: Story = {
    args: {
        result: { ...result, value: true },
        scorer: { ...result.scorer, kind: 'boolean', config: { true_is_failure: true } },
    },
}
export const UnconfiguredBoolean: Story = {
    args: {
        result: { ...result, value: true },
        scorer: { ...result.scorer, kind: 'boolean', config: {} },
    },
}
export const Skipped: Story = { args: { result: { ...result, status: 'skipped', value: null } } }
export const Error: Story = { args: { result: { ...result, status: 'error', value: null } } }

export const NearThreshold: Story = {
    args: {
        result: { ...result, value: 0.9999999 },
        scorer: { ...result.scorer, kind: 'numeric', config: { passing_rule: { operator: 'gte', threshold: 1 } } },
    },
}
export const CategoricalMixed: Story = {
    args: {
        result: { ...result, value: ['good', 'bad'] },
        scorer: {
            ...result.scorer,
            kind: 'categorical',
            config: {
                options: [
                    { key: 'good', label: 'Good' },
                    { key: 'bad', label: 'Bad' },
                ],
                selection_mode: 'multiple',
                passing_rule: { categories: ['good'] },
            },
        },
    },
}
