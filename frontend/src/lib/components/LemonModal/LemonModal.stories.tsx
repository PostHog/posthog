import React, { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonModal, LemonModalProps } from './LemonModal'
import { LemonButton } from '../LemonButton'

export default {
    title: 'Lemon UI/Lemon Modal',
    component: LemonModal,
} as ComponentMeta<typeof LemonModal>

export const _LemonModal: ComponentStory<typeof LemonModal> = (props: LemonModalProps) => {
    const [isOpen, setIsOpen] = useState(false)
    return (
        <>
            <LemonButton type="primary" onClick={() => setIsOpen(true)}>
                Show control panel
            </LemonButton>
            <LemonModal visible={isOpen} onCancel={() => setIsOpen(false)} {...props}>
                <section>
                    <h5>Adventure zone</h5>
                    <LemonButton type="primary">Go into hyperspace</LemonButton>
                </section>
                <section>
                    <h5>Danger zone</h5>
                    <LemonButton type="secondary" status="danger">
                        Initiate self-destruct sequence
                    </LemonButton>
                </section>
            </LemonModal>
        </>
    )
}
