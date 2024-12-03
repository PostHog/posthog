import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { UploadedLogo, UploadedLogoProps } from './UploadedLogo'

type Story = StoryObj<typeof UploadedLogo>
const meta: Meta<typeof UploadedLogo> = {
    title: 'Lemon UI/Uploaded Logo',
    component: UploadedLogo,
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
    tags: ['autodocs'],
}
export default meta

const MediaTemplate: StoryFn<typeof UploadedLogo> = (props: UploadedLogoProps) => {
    return <UploadedLogo {...props} entityId={1} />
}

const LettermarkTemplate: StoryFn<typeof UploadedLogo> = (props: UploadedLogoProps) => {
    return (
        <div className="flex flex-col gap-1">
            <UploadedLogo {...props} entityId={1} />
            <UploadedLogo {...props} entityId={2} />
            <UploadedLogo {...props} entityId={3} />
            <UploadedLogo {...props} entityId={4} />
        </div>
    )
}

const POSTHOG_LOGO_32 =
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAABOklEQVR4AazPw182URQH8Hn1X7xax13e1SbbNjfZdrvMdXabuMm2bdetQa7TM+fJ1uD6fs/nRxGyablLNsku2YB3/nM0vWlJ8QNc+NhPeAA+838NIG15BsNTW0CmuoF1EwOyMgVkYwC4Ps+3AX9UAJGRtl7gNChE9uaa4LhBFJFXAb9kDhEly22gE4yEiKckcEMhiLCC/tUIrnGHIKM6B6zNHyFi9gsOWzUROegwhdjYyNcjxMSP8dURYTLM+eqI0PMl8PfvHzAxMXwaSMqjH0dw/g9cvwciXI8DAhRFIfJkhOgc9lGEoyZFRAQREEhNS0JEQUEOKqvKbgEdz2PwS+KgrnIAGB95oFMcgS4OwIvsaALsL9WAqqqK4OLlrGEYyPeEGTDwKRGRE8nJkcDs/DyBnBwJsvgNUC8A9bVkZEv0zlAAAAAASUVORK5CYII='

export const Base: Story = MediaTemplate.bind({})
Base.args = { name: 'Athena', mediaId: POSTHOG_LOGO_32 }

export const ExtraSmall: Story = MediaTemplate.bind({})
ExtraSmall.args = { name: 'Xtra', mediaId: POSTHOG_LOGO_32, size: 'xsmall' }

export const ExtraLarge: Story = MediaTemplate.bind({})
ExtraLarge.args = { name: 'Xtra', mediaId: POSTHOG_LOGO_32, size: 'xlarge' }

export const BaseWithoutMedia: Story = LettermarkTemplate.bind({})
BaseWithoutMedia.args = { name: 'Athena' }

export const ExtraSmallWithoutMedia: Story = LettermarkTemplate.bind({})
ExtraSmallWithoutMedia.args = { name: 'Xtra', size: 'xsmall' }

export const ExtraLargeWithoutMedia: Story = LettermarkTemplate.bind({})
ExtraLargeWithoutMedia.args = { name: 'Xtra', size: 'xlarge' }
