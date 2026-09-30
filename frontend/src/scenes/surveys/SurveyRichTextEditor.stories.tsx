import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { SurveyQuestionDescriptionContentType } from '~/types'

import { HTMLEditor } from './SurveyAppearanceUtils'

type StoryArgs = { value: string; contentType: SurveyQuestionDescriptionContentType }
type Story = StoryObj<StoryArgs>

const meta: Meta<StoryArgs> = {
    title: 'Scenes-App/Surveys/Description editor',
    parameters: {
        featureFlags: [FEATURE_FLAGS.SURVEYS_RICH_TEXT_DESCRIPTIONS],
    },
    render: (args): JSX.Element => {
        const [value, setValue] = useState(args.value)
        const [contentType, setContentType] = useState(args.contentType)
        return (
            <div className="max-w-120">
                <HTMLEditor value={value} onChange={setValue} activeTab={contentType} onTabChange={setContentType} />
            </div>
        )
    },
}

export default meta

export const RichText: Story = {
    args: {
        value: '<p>We read <strong>every</strong> answer.</p><p>It takes <em>one minute</em>.</p>',
        contentType: 'html',
    },
}

export const UnsupportedHTML: Story = {
    args: {
        value: '<div style="color: red">Custom HTML</div>',
        contentType: 'html',
    },
}

export const PlainText: Story = {
    args: { value: 'Tell us more', contentType: 'text' },
}
