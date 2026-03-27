import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { LemonDrawer, LemonDrawerProps } from './LemonDrawer'

const meta: Meta<LemonDrawerProps> = {
    title: 'Lemon UI/Lemon Drawer',
    component: LemonDrawer,
    tags: ['autodocs'],
}
export default meta

type Story = StoryObj<LemonDrawerProps>

export const _LemonDrawer: Story = {
    render: () => {
        const [isOpen, setIsOpen] = useState(false)
        return (
            <>
                <LemonButton type="primary" onClick={() => setIsOpen(true)}>
                    Open drawer
                </LemonButton>
                <LemonDrawer
                    isOpen={isOpen}
                    onClose={() => setIsOpen(false)}
                    title="Drawer title"
                    description="Helpful description content here"
                    footer={
                        <>
                            <LemonButton type="secondary">Cancel</LemonButton>
                            <LemonButton type="primary">Save</LemonButton>
                        </>
                    }
                >
                    <p>
                        Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut
                        labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco
                        laboris nisi ut aliquip ex ea commodo consequat.
                    </p>
                    <p>
                        Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla
                        pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt
                        mollit anim id est laborum.
                    </p>
                </LemonDrawer>
            </>
        )
    },
}

export const TransparentOverlay: Story = {
    render: () => {
        const [isOpen, setIsOpen] = useState(false)
        return (
            <>
                <LemonButton type="primary" onClick={() => setIsOpen(true)}>
                    Open drawer (transparent overlay)
                </LemonButton>
                <LemonDrawer
                    isOpen={isOpen}
                    onClose={() => setIsOpen(false)}
                    title="Transparent overlay"
                    description="The content behind the drawer remains fully visible"
                    overlayTransparent
                >
                    <p>This drawer has no backdrop blur or darkening.</p>
                </LemonDrawer>
            </>
        )
    },
}

export const CustomWidth: Story = {
    render: () => {
        const [isOpen, setIsOpen] = useState(false)
        return (
            <>
                <LemonButton type="primary" onClick={() => setIsOpen(true)}>
                    Open wide drawer
                </LemonButton>
                <LemonDrawer isOpen={isOpen} onClose={() => setIsOpen(false)} title="Wide drawer" width="60vw">
                    <p>This drawer uses a custom width of 60vw.</p>
                </LemonDrawer>
            </>
        )
    },
}

export const WithCustomContent: Story = {
    render: () => {
        const [isOpen, setIsOpen] = useState(false)
        return (
            <>
                <LemonButton type="primary" onClick={() => setIsOpen(true)}>
                    Open custom drawer
                </LemonButton>
                <LemonDrawer isOpen={isOpen} onClose={() => setIsOpen(false)} simple aria-label="Custom drawer">
                    <LemonDrawer.Header>
                        <h3>Custom header</h3>
                    </LemonDrawer.Header>
                    <LemonDrawer.Content>
                        Using the <code>simple</code> prop, you can compose the drawer layout yourself with{' '}
                        <code>LemonDrawer.Header</code>, <code>LemonDrawer.Content</code>, and{' '}
                        <code>LemonDrawer.Footer</code>.
                    </LemonDrawer.Content>
                    <LemonDrawer.Footer>
                        <LemonButton type="secondary" onClick={() => setIsOpen(false)}>
                            Close
                        </LemonButton>
                    </LemonDrawer.Footer>
                </LemonDrawer>
            </>
        )
    },
}
