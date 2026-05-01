import type { Meta, StoryObj } from '@storybook/react'

import { Badge } from './badge'
import { InfoIcon } from 'lucide-react'
import { Spinner } from './spinner'

const meta = {
    title: 'Primitives/Badge',
    component: Badge,
    tags: ['autodocs'],
    argTypes: {
        variant: {
            control: 'select',
            options: ['default', 'secondary', 'destructive', 'outline', 'ghost'],
        },
    },
} satisfies Meta<typeof Badge>

export default meta
type Story = StoryObj<typeof meta>

export const Default = {
    render: () => (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-2">
                <Badge variant="default">Default</Badge>
                <Badge variant="info">Info</Badge>
                <Badge variant="destructive">Destructive</Badge>
                <Badge variant="warning">Warning</Badge>
                <Badge variant="success">Success</Badge>
            </div>
        </div>
    ),
} satisfies Story

export const WithIcons = {
    render: () => (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-2">
                <Badge variant="default"><InfoIcon data-icon="inline-start"/> Default</Badge>
                <Badge variant="default"><Spinner data-icon="inline-start"/> Spinner</Badge>
            </div>
            <div className="flex flex-wrap gap-2">
                <Badge variant="default">Default <InfoIcon data-icon="inline-end"/></Badge>
                <Badge variant="default">Spinner <Spinner data-icon="inline-end"/></Badge>
            </div>
        </div>
    ),
} satisfies Story