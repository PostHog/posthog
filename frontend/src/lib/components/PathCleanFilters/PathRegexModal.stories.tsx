import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { FEATURE_FLAGS } from 'lib/constants'
import { useState } from 'react'

import { PathCleaningFilter } from '~/types'

import { PathRegexModal, PathRegexModalProps } from './PathRegexModal'

type Story = StoryObj<typeof PathRegexModal>
const meta: Meta<typeof PathRegexModal> = {
    title: 'Filters/PathRegexModal',
    component: PathRegexModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta

const Template: StoryFn<typeof PathRegexModal> = (props: Pick<PathRegexModalProps, 'filter'>) => {
    const [isOpen, setIsOpen] = useState(true)

    return (
        <>
            <span onClick={() => setIsOpen(true)}>Click to open modal</span>
            <PathRegexModal
                isOpen={isOpen}
                onClose={() => setIsOpen(false)}
                onSave={(filter: PathCleaningFilter) => {
                    // Testing purposes only
                    // eslint-disable-next-line no-console
                    console.log('Saved filter:', filter)

                    setIsOpen(false)
                }}
                {...props}
            />
        </>
    )
}

export const NewRule: Story = Template.bind({})
NewRule.args = {}

export const EditExistingRule: Story = Template.bind({})
EditExistingRule.args = {
    filter: {
        alias: 'merchant_id',
        regex: '/merchant/\\d+/dashboard$',
    },
}

export const WithAIHelper: Story = Template.bind({})
WithAIHelper.args = {}
WithAIHelper.parameters = {
    featureFlags: [FEATURE_FLAGS.PATH_CLEANING_AI_REGEX],
}
