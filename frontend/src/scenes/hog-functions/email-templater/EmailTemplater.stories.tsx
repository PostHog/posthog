import { Meta, StoryFn } from '@storybook/react'
import { useValues } from 'kea'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { mswDecorator } from '~/mocks/browser'

import { EmailPreviewPerson } from './emailPreview'
import { EmailTemplater } from './EmailTemplater'
import { EmailTemplate } from './emailTemplaterLogic'

const EMAIL: EmailTemplate = {
    design: null,
    html: '<div style="font-family: sans-serif"><p>Hi {{ person.properties.first_name }},</p><p>Your {{ person.properties.plan }} plan renews soon.</p></div>',
    subject: 'Hi {{ person.properties.first_name }}, your plan renews soon',
    preheader: 'A quick note about {{ person.properties.plan }}',
    text: '',
    from: { integrationId: 1 },
    to: { email: '{{ person.properties.email }}' } as unknown as string,
}

const PERSON: EmailPreviewPerson = {
    id: '0192f0e1-1111-1111-1111-111111111111',
    properties: { email: 'sam@example.com', first_name: 'Sam' },
}

const meta: Meta<typeof EmailTemplater> = {
    title: 'Scenes-App/Hog Functions/Email templater',
    component: EmailTemplater,
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/messaging_templates/': { results: [] },
                '/api/projects/:team_id/property_definitions/': { results: [] },
            },
        }),
    ],
}
export default meta

const Template: StoryFn<{ previewPerson: EmailPreviewPerson | null }> = ({ previewPerson }) => {
    // The templater reads the realm off preflight, so mount it before rendering one.
    const { preflight } = useValues(preflightLogic)

    return (
        // Pinned to the width a step panel gives the preview in a narrow scene
        <div className="flex flex-col w-[420px] h-[420px]">
            {preflight && (
                <EmailTemplater
                    type="native_email"
                    templating="liquid"
                    value={EMAIL}
                    onChange={() => {}}
                    previewPerson={previewPerson}
                />
            )}
        </div>
    )
}

export const PreviewedAgainstAPerson: StoryFn<{ previewPerson: EmailPreviewPerson | null }> = Template.bind({})
PreviewedAgainstAPerson.args = { previewPerson: PERSON }

export const NoPersonToPreviewAgainst: StoryFn<{ previewPerson: EmailPreviewPerson | null }> = Template.bind({})
NoPersonToPreviewAgainst.args = { previewPerson: null }
