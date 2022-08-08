import React, { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonModal, LemonModalProps } from './LemonModal'
import { LemonButton } from '../LemonButton'

export default {
    title: 'Lemon UI/LemonModal',
    component: LemonModal,
} as ComponentMeta<typeof LemonModal>

export const _LemonModal: ComponentStory<typeof LemonModal> = (props: LemonModalProps) => {
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
