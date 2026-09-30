import type { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { mswDecorator } from '~/mocks/browser'

import { PropertyAccessRules } from './PropertyAccessRules'

const meta: Meta<typeof PropertyAccessRules> = {
    title: 'Scenes-Other/Access control/Property rules',
    component: PropertyAccessRules,
    parameters: { layout: 'padded' },
    args: { projectId: '997', scopeType: 'default', subjectId: '', subjectNoun: 'project', canEdit: true },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/access_control_default_objects': { results: [] },
                '/api/projects/:id/access_control_default_properties': {
                    results: [
                        {
                            property_definition_id: 'input-rule',
                            property: '$ai_input',
                            property_type: 'event',
                            access_level: 'none',
                        },
                        {
                            property_definition_id: 'output-rule',
                            property: '$ai_output_choices',
                            property_type: 'event',
                            access_level: 'none',
                        },
                        {
                            property_definition_id: 'person-rule',
                            property: 'email',
                            property_type: 'person',
                            access_level: 'read',
                        },
                    ],
                },
                '/api/projects/:id/property_definitions/': { results: [] },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {}

export const AIPropertyPicker: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByText('Add rule'))
        const page = within(document.body)
        await userEvent.click(
            await page.findByText('Person property', { selector: '[data-attr="property-rule-type"] *' })
        )
        await userEvent.click(await page.findByRole('button', { name: 'Person property' }))
        await userEvent.click(await page.findByRole('menuitem', { name: 'ai_events property' }))
        await userEvent.type(await page.findByPlaceholderText('Search by name…'), 'output')
        await page.findByRole('button', { name: 'output_choices ($ai_output_choices)' })
    },
}

export const SavingAIPropertyRule: Story = {
    parameters: {
        testOptions: { waitForLoadersToDisappear: false },
        msw: {
            mocks: {
                post: {
                    '/api/projects/:id/property_access_controls/': () => new Promise<never>(() => {}),
                },
            },
        },
    },
    play: async (context) => {
        await AIPropertyPicker.play?.(context)
        const page = within(document.body)
        await userEvent.click(await page.findByRole('button', { name: 'output ($ai_output)' }))
        const dialog = within(page.getByRole('dialog'))
        await waitFor(() => {
            if (dialog.getByRole('button', { name: 'Add rule' }).getAttribute('aria-disabled') === 'true') {
                throw new Error('Waiting for property selection')
            }
        })
        await userEvent.click(dialog.getByRole('button', { name: 'Add rule' }))
    },
}

export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="max-w-lg">
                <Story />
            </div>
        ),
    ],
}
