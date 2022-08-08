import React, { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonModalV2, LemonModalV2Props } from './LemonModalV2'
import { LemonButton } from '../LemonButton'

export default {
    title: 'Lemon UI/LemonModalV2',
    component: LemonModalV2,
} as ComponentMeta<typeof LemonModalV2>

export const _LemonModalV2: ComponentStory<typeof LemonModalV2> = (props: LemonModalV2Props) => {
    const [isOpen, setIsOpen] = useState(false)
    return (
        <>
            <LemonButton type="primary" onClick={() => setIsOpen(true)}>
                Show control panel
            </LemonButton>
            <LemonModalV2
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
            </LemonModalV2>
        </>
    )
}
