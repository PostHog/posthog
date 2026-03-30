import type { Meta, StoryObj } from '@storybook/react'

import { UploadedLogo, UploadedLogoProps } from './UploadedLogo'

type Story = StoryObj<UploadedLogoProps>
const meta: Meta<UploadedLogoProps> = {
    title: 'Lemon UI/Uploaded Logo',
    component: UploadedLogo as any,
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
    tags: ['autodocs'],
}
export default meta

const renderMediaLogo = (props: UploadedLogoProps): JSX.Element => {
    return <UploadedLogo {...props} entityId={1} />
}

const renderLettermarkLogo = (props: UploadedLogoProps): JSX.Element => {
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

export const Base: Story = {
    render: renderMediaLogo,
    args: { name: 'Athena', mediaId: POSTHOG_LOGO_32 },
}

export const ExtraSmall: Story = {
    render: renderMediaLogo,
    args: { name: 'Xtra', mediaId: POSTHOG_LOGO_32, size: 'xsmall' },
}

export const ExtraLarge: Story = {
    render: renderMediaLogo,
    args: { name: 'Xtra', mediaId: POSTHOG_LOGO_32, size: 'xlarge' },
}

export const BaseWithoutMedia: Story = {
    render: renderLettermarkLogo,
    args: { name: 'Athena' },
}

export const ExtraSmallWithoutMedia: Story = {
    render: renderLettermarkLogo,
    args: { name: 'Xtra', size: 'xsmall' },
}

export const ExtraLargeWithoutMedia: Story = {
    render: renderLettermarkLogo,
    args: { name: 'Xtra', size: 'xlarge' },
}
