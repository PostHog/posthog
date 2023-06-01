import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonBanner, LemonBannerProps } from './LemonBanner'

export default {
    title: 'Lemon UI/Lemon Banner',
    component: LemonBanner,
    parameters: {
        actions: {
            // See https://github.com/storybookjs/addon-smart-knobs/issues/63#issuecomment-995798227
            argTypesRegex: null,
        },
    },
} as ComponentMeta<typeof LemonBanner>

const Template: ComponentStory<typeof LemonBanner> = (props: LemonBannerProps) => {
    return <LemonBanner {...props} />
}

export const Info = Template.bind({})
Info.args = { type: 'info', children: 'PSA: Every dish can be improved by adding more garlic.' }

export const Warning = Template.bind({})
Warning.args = { type: 'warning', children: 'This spacecraft is about to explode. Please evacuate immediately.' }

export const Error = Template.bind({})
Error.args = { type: 'error', children: 'This spacecraft has exploded. Too late...' }

export const Success = Template.bind({})
Success.args = { type: 'success', children: 'This spacecraft has recovered. Phew!' }

export const Closable = Template.bind({})
Closable.args = {
    type: 'info',
    children: 'This is a one-time message. Acknowledge it and move on with your life.',
    onClose: () => alert('👋'),
}

export const Dismissable = Template.bind({})
Dismissable.args = {
    type: 'info',
    children: 'If you dismiss this message, it will be gone forever. (Clear the localstorage key to get it back)',
    dismissKey: 'storybook-banner',
    onClose: () => alert('👋'),
}
