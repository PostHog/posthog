import type { Meta, StoryObj } from '@storybook/react'

import { SrmCause } from '~/queries/schema/schema-general'

import { getExposureSplitVerdict } from './exposureSplitVerdict'
import { ExposureSplitVerdictTag } from './ExposureSplitVerdictTag'

type Story = StoryObj<typeof ExposureSplitVerdictTag>
const meta: Meta<typeof ExposureSplitVerdictTag> = {
    title: 'Scenes-App/Experiments/ExposureSplitVerdictTag',
    component: ExposureSplitVerdictTag,
}
export default meta

const EXPECTED = { control: 5000, test: 5000 }

export const MatchesRollout: Story = {
    args: { verdict: getExposureSplitVerdict({ expected: EXPECTED, p_value: 0.42 })! },
}

export const Mismatch: Story = {
    args: {
        verdict: getExposureSplitVerdict({
            expected: EXPECTED,
            p_value: 4.7e-11,
            diagnosis: { cause: SrmCause.LowSampleSize, smallest_expected_count: 250 },
        })!,
    },
}
