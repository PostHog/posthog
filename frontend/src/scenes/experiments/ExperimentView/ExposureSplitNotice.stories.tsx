import type { Meta, StoryObj } from '@storybook/react'

import { SampleRatioMismatch, SrmCause } from '~/queries/schema/schema-general'

import { ExposureSplitNotice } from './ExposureSplitNotice'
import { getExposureSplitVerdict } from './exposureSplitVerdict'

type Story = StoryObj<typeof ExposureSplitNotice>
const meta: Meta<typeof ExposureSplitNotice> = {
    title: 'Scenes-App/Experiments/ExposureSplitNotice',
    component: ExposureSplitNotice,
    // LemonBanner is a CSS container, so its width has to come from a parent to show how the
    // notice reflows in a narrow scene.
    decorators: [
        (Story) => (
            <div className="w-160">
                <Story />
            </div>
        ),
    ],
}
export default meta

function story(mismatch: SampleRatioMismatch): Story {
    return {
        args: {
            verdict: getExposureSplitVerdict(mismatch)!,
            pValue: mismatch.p_value,
            onEditExposureCriteria: () => {},
        },
    }
}

const EXPECTED = { control: 5000, test: 5000 }

export const MatchesRollout: Story = story({ expected: EXPECTED, p_value: 0.42 })

export const LowSampleSize: Story = story({
    expected: { control: 250, test: 250 },
    p_value: 6.3e-4,
    diagnosis: { cause: SrmCause.LowSampleSize, smallest_expected_count: 250 },
})

export const CaptureBySurface: Story = story({
    expected: EXPECTED,
    p_value: 4.7e-11,
    diagnosis: {
        cause: SrmCause.CaptureBySurface,
        surface_skew: {
            surface: '/checkout',
            variant: 'test',
            variant_percentage: 99,
            expected_percentage: 50,
            exposures: 2000,
        },
    },
})

export const UnknownCause: Story = story({
    expected: EXPECTED,
    p_value: 4.7e-11,
    diagnosis: { cause: SrmCause.Unknown },
})
