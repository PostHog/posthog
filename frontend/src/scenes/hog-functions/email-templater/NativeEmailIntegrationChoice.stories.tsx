import { Meta, StoryFn } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { LemonLabel } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'

import { useStorybookMocks } from '~/mocks/browser'

import { NativeEmailIntegrationChoice } from './EmailTemplater'
import { EmailTemplaterLogicProps, emailTemplaterLogic } from './emailTemplaterLogic'
import { EmailTemplate, EmailTemplateFrom } from './types'

const SANDBOX_SENDER = {
    id: 7,
    kind: 'email',
    display_name: 'Acme via PostHog <sandbox@example.com>',
    config: { provider: 'sandbox', name: 'Acme via PostHog', email: 'sandbox@example.com', verified: true },
    created_at: '2026-08-18T00:00:00Z',
}

const OWN_SENDER = {
    id: 8,
    kind: 'email',
    display_name: 'Acme <hello@acme.example.com>',
    config: {
        provider: 'ses',
        name: 'Acme',
        email: 'hello@acme.example.com',
        domain: 'acme.example.com',
        verified: true,
    },
    created_at: '2026-08-18T00:00:00Z',
}

type StoryArgs = {
    from: EmailTemplateFrom
    sandboxSenderAllowed: boolean
    narrow?: boolean
}

const EMPTY_EMAIL: EmailTemplate = { design: null, html: '', subject: '', text: '', from: {}, to: '' }

const meta: Meta<StoryArgs> = {
    title: 'Scenes-App/HogFunctions/Email sender picker',
    parameters: { layout: 'padded', viewMode: 'story' },
}
export default meta

const Template: StoryFn<StoryArgs> = ({ from, sandboxSenderAllowed, narrow }) => {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/integrations/': { results: [SANDBOX_SENDER, OWN_SENDER] },
            '/api/environments/:team_id/messaging_templates/': { results: [] },
            '/api/projects/:team_id/property_definitions/': { results: [] },
        },
        post: { '/api/projects/:team_id/integrations/email_sandbox_sender/': SANDBOX_SENDER },
    })
    const [template, setTemplate] = useState<EmailTemplate>({ ...EMPTY_EMAIL, from })
    const logicProps: EmailTemplaterLogicProps = {
        value: template,
        onChange: setTemplate,
        type: 'native_email',
        liveChanges: true,
        sandboxSenderAllowed,
    }
    return (
        <BindLogic logic={emailTemplaterLogic} props={logicProps}>
            <div className={narrow ? 'w-[520px] border rounded' : 'max-w-2xl border rounded'}>
                <NativeEmailIntegrationChoice
                    label={<LemonLabel className="min-w-30 shrink-0 pl-2">From</LemonLabel>}
                    value={template.from as EmailTemplateFrom}
                    onChange={(from) => setTemplate({ ...template, from })}
                />
            </div>
        </BindLogic>
    )
}

const sandboxFlag = (rotation: boolean): string[] =>
    rotation
        ? [FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER, FEATURE_FLAGS.WORKFLOWS_EMAIL_SENDER_ROTATION]
        : [FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER]

export const OwnSenderSelected: StoryFn<StoryArgs> = Template.bind({})
OwnSenderSelected.args = { from: { integrationId: OWN_SENDER.id }, sandboxSenderAllowed: true }
OwnSenderSelected.parameters = { featureFlags: sandboxFlag(false) }

export const SandboxSenderSelected: StoryFn<StoryArgs> = Template.bind({})
SandboxSenderSelected.args = { from: { integrationId: SANDBOX_SENDER.id }, sandboxSenderAllowed: true }
SandboxSenderSelected.parameters = { featureFlags: sandboxFlag(false) }

export const SandboxSenderSelectedInRotation: StoryFn<StoryArgs> = Template.bind({})
SandboxSenderSelectedInRotation.args = {
    from: { integrationId: SANDBOX_SENDER.id },
    sandboxSenderAllowed: true,
}
SandboxSenderSelectedInRotation.parameters = { featureFlags: sandboxFlag(true) }

export const SandboxSenderSelectedInRotationNarrow: StoryFn<StoryArgs> = Template.bind({})
SandboxSenderSelectedInRotationNarrow.args = {
    from: { integrationId: SANDBOX_SENDER.id },
    sandboxSenderAllowed: true,
    narrow: true,
}
SandboxSenderSelectedInRotationNarrow.parameters = { featureFlags: sandboxFlag(true) }

export const SandboxSenderHiddenOnBroadcast: StoryFn<StoryArgs> = Template.bind({})
SandboxSenderHiddenOnBroadcast.args = {
    from: { integrationId: OWN_SENDER.id },
    sandboxSenderAllowed: false,
}
SandboxSenderHiddenOnBroadcast.parameters = { featureFlags: sandboxFlag(false) }
