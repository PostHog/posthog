import type { Meta, StoryObj } from '@storybook/react'
import { ArrowRightIcon, Folder } from 'lucide-react'

import { Button } from './button'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from './empty'

const meta: Meta<typeof Empty> = {
    title: 'Primitives/Empty/Empty',
    component: Empty,
    tags: ['autodocs'],
}

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <Folder />
                    </EmptyMedia>
                    <EmptyTitle>No Projects yet</EmptyTitle>
                    <EmptyDescription>
                        You haven't created any projects yet. Get started by creating your first project.
                    </EmptyDescription>
                </EmptyHeader>
                <EmptyContent className="flex-row justify-center gap-2">
                    <Button>Create Project</Button>
                    <Button variant="outline">Import Project</Button>
                </EmptyContent>
                <Button
                    variant="link-muted"
                    size="sm"
                    render={
                        // eslint-disable-next-line react/forbid-elements
                        <a href="#">
                            Learn More <ArrowRightIcon />
                        </a>
                    }
                />
            </Empty>
        )
    },
}
