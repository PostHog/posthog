import { Meta, StoryFn } from '@storybook/react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { mswDecorator } from '~/mocks/browser'

import { ProvisionedWelcomeMessage } from './projectNoticeLogic'

// The project notice picks its variant from a long chain of logic inputs, so rather than mock all of
// them we render the provisioned-welcome banner exactly as ProjectNotice does: the message inside a
// LemonBanner. This keeps the flagship-product hog strip reviewable in CI.
const meta: Meta = {
    title: 'Layout/Project Notice',
    parameters: {
        layout: 'padded',
    },
    decorators: [mswDecorator({})],
}
export default meta

export const ProvisionedWelcome: StoryFn = () => (
    <LemonBanner type="info" onClose={() => {}}>
        <ProvisionedWelcomeMessage />
    </LemonBanner>
)
