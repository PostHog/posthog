import { Meta, StoryFn } from '@storybook/react'
import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { LemonModal, LemonModalProps } from './LemonModal'

const meta: Meta<typeof LemonModal> = {
    title: 'Lemon UI/Lemon Modal',
    component: LemonModal,
    tags: ['autodocs'],
}
export default meta

export const _LemonModal: StoryFn<typeof LemonModal> = (props: LemonModalProps) => {
    const [isOpen, setIsOpen] = useState(false)
    return (
        <>
            <LemonButton type="primary" onClick={() => setIsOpen(true)}>
                Show control panel
            </LemonButton>
            <LemonModal
                {...props}
                isOpen={isOpen}
                onClose={() => setIsOpen(false)}
                title="My Amazing Modal"
                description="Helpful description content here"
                footer={
                    <>
                        <div className="flex-1">
                            <LemonButton type="secondary">Tertiary action</LemonButton>
                        </div>
                        <LemonButton type="secondary">Secondary</LemonButton>
                        <LemonButton type="primary">Primary</LemonButton>
                    </>
                }
            >
                <p>
                    Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore
                    et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut
                    aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse
                    cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in
                    culpa qui officia deserunt mollit anim id est laborum.
                </p>

                <p>
                    Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore
                    et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut
                    aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse
                    cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in
                    culpa qui officia deserunt mollit anim id est laborum.
                </p>

                <p>
                    Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore
                    et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut
                    aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse
                    cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in
                    culpa qui officia deserunt mollit anim id est laborum.
                </p>
            </LemonModal>
        </>
    )
}

export const WithoutContent: StoryFn<typeof LemonModal> = (props: LemonModalProps) => {
    const [isOpen, setIsOpen] = useState(false)
    return (
        <>
            <LemonButton type="primary" onClick={() => setIsOpen(true)}>
                Show control panel
            </LemonButton>
            <LemonModal
                {...props}
                isOpen={isOpen}
                onClose={() => setIsOpen(false)}
                title="I don't have content"
                description="But thats okay"
                footer={
                    <>
                        <div className="flex-1">
                            <LemonButton type="secondary">Tertiary action</LemonButton>
                        </div>
                        <LemonButton type="secondary">Secondary</LemonButton>
                        <LemonButton type="primary">Primary</LemonButton>
                    </>
                }
            />
        </>
    )
}

export const Inline: StoryFn<typeof LemonModal> = () => {
    const [isOpen, setIsOpen] = useState(false)
    return (
        <div className="bg-default p-4">
            <LemonModal
                isOpen={isOpen}
                onClose={() => setIsOpen(false)}
                title="Inline Modals"
                description="You can display modal inline (i.e. just the content, no actual modal. This is mostly useful for creating Storybooks of modals"
                inline
                footer={
                    <>
                        <LemonButton type="secondary">Amazing</LemonButton>
                    </>
                }
            >
                If you use this pattern in a Story for a modal, it is recommended to wrap it in a div with a dark
                background (like this example)
            </LemonModal>
        </div>
    )
}

export const WithCustomContent: StoryFn<typeof LemonModal> = () => {
    const [isOpen, setIsOpen] = useState(false)
    return (
        <div className="bg-default p-4">
            <LemonModal
                isOpen={isOpen}
                onClose={() => setIsOpen(false)}
                title="Inline Modals"
                description="You can display modal inline (i.e. just the content, no actual modal. This is mostly useful for creating Storybooks of modals"
                inline
                simple
            >
                <div className="rounded">
                    <LemonModal.Header>
                        <h3>I am a custom header</h3>
                    </LemonModal.Header>
                    <LemonModal.Content>
                        In some situations it may be necessary to have greater control over the modal contents. The most
                        common use case is <b>Forms with submit buttons in the footer</b>. Using the <code>simple</code>{' '}
                        property on the modal you can implement the Header, Footer and Content components yourself. See
                        this story's code for the example
                    </LemonModal.Content>
                    <LemonModal.Footer>
                        <p>I am a custom footer</p>
                    </LemonModal.Footer>
                </div>
            </LemonModal>
        </div>
    )
}
