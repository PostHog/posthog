import { Meta } from '@storybook/react'

import { KeyboardShortcut } from './KeyboardShortcut'

const meta: Meta<typeof KeyboardShortcut> = {
    title: 'PostHog 3000/Keyboard Shortcut',
    component: KeyboardShortcut,
    tags: ['autodocs'],
}
export default meta

export const Default = {
    args: {
        cmd: true,
        shift: true,
        k: true,
    },
}

export const Muted = {
    args: {
        muted: true,
        cmd: true,
        shift: true,
        k: true,
    },
}
