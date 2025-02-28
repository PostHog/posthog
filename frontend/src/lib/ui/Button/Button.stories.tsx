import { IconBell } from '@posthog/icons'
import { Meta } from '@storybook/react'

import { Button } from './Button'

const meta: Meta<typeof Button> = {
    title: 'UI/Button',
    component: Button,
    args: {},
    tags: ['autodocs'],
}
export default meta

export function Default(): JSX.Element {
    return (
        <div className="space-y-2">
            <div className="flex flex-col gap-2 p-8 bg-white dark:bg-black">
                <Button>Default</Button>
                <Button active>Default active</Button>
                <Button iconLeft={{ icon: <IconBell />, size: 'default' }}>Default with icon</Button>
                <Button iconRight={{ icon: <IconBell />, size: 'default' }}>Default with icon</Button>
            </div>

            <div className="flex flex-col gap-2 p-8 bg-black dark:bg-white">
                <Button variant="default-inverse">Default inverse</Button>
                <Button variant="default-inverse" active>
                    Default inverse active
                </Button>
                <Button iconLeft={{ icon: <IconBell />, size: 'default' }} variant="default-inverse">
                    Default inverse with icon
                </Button>
                <Button iconRight={{ icon: <IconBell />, size: 'default' }} variant="default-inverse">
                    Default inverse with icon
                </Button>
            </div>
        </div>
    )
}
