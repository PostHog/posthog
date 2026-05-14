import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconLock, IconShieldLock } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { agentApplicationLogic } from '../agentApplicationLogic'

export function AgentApplicationSettings(): JSX.Element {
    const { application, isSettingsSubmitting } = useValues(agentApplicationLogic)
    const { resetSettings } = useActions(agentApplicationLogic)

    if (!application) {
        return (
            <div className="as-mono text-xs" style={{ color: 'var(--as-text-dim)' }}>
                // loading…
            </div>
        )
    }

    return (
        <Form
            id="agent-application-settings"
            formKey="settings"
            logic={agentApplicationLogic}
            className="grid grid-cols-1 lg:grid-cols-5 gap-8"
        >
            {/* Left column — app metadata */}
            <div className="flex flex-col gap-5 lg:col-span-2">
                <div>
                    <div className="as-label mb-2">▌ Manifest</div>
                    <p className="as-mono text-xs my-0" style={{ color: 'var(--as-text-dim)' }}>
                        // display fields are mutable · slug is permanent
                    </p>
                </div>

                <LemonField name="name" label={<span className="as-label">// Name</span>}>
                    {({ value, onChange }) => (
                        <input
                            className="as-input"
                            value={value ?? ''}
                            onChange={(e) => onChange(e.target.value)}
                            placeholder="standup-bot"
                        />
                    )}
                </LemonField>

                <LemonField name="description" label={<span className="as-label">// Description</span>}>
                    {({ value, onChange }) => (
                        <textarea
                            className="as-textarea"
                            value={value ?? ''}
                            onChange={(e) => onChange(e.target.value)}
                            placeholder="What does this agent do?"
                            style={{ minHeight: 100 }}
                        />
                    )}
                </LemonField>

                <div className="flex flex-col gap-1">
                    <div className="as-label">// Slug · immutable</div>
                    <code className="as-mono text-sm" style={{ color: 'var(--as-text)' }}>
                        {application.slug}
                    </code>
                    <span className="as-mono text-xs" style={{ color: 'var(--as-text-dim)' }}>
                        // delete and recreate to reroute
                    </span>
                </div>
            </div>

            {/* Right column — env */}
            <div className="flex flex-col gap-5 lg:col-span-3">
                <div className="flex items-center gap-2">
                    <IconShieldLock style={{ color: 'var(--as-live)' }} />
                    <div className="as-label as-label-accent">▌ Environment</div>
                </div>

                <div>
                    <div className="as-label mb-2 flex items-center gap-2">
                        <IconLock />
                        // Currently set keys
                    </div>
                    {application.env_redacted ? (
                        <pre className="as-env-readout m-0">{application.env_redacted}</pre>
                    ) : (
                        <p className="as-mono text-xs italic m-0" style={{ color: 'var(--as-text-dim)' }}>
                            // no env configured yet
                        </p>
                    )}
                </div>

                <LemonField
                    name="env"
                    label={<span className="as-label">// Replace env</span>}
                    help={
                        <p className="as-mono text-xs my-1" style={{ color: 'var(--as-text-dim)' }}>
                            // paste a new .env to replace the current one · empty input keeps existing values ·
                            plaintext never leaves the server
                        </p>
                    }
                >
                    {({ value, onChange }) => (
                        <textarea
                            className="as-textarea"
                            value={value ?? ''}
                            onChange={(e) => onChange(e.target.value)}
                            placeholder={'ANTHROPIC_API_KEY=sk-...\nSLACK_BOT_TOKEN=xoxb-...'}
                            spellCheck={false}
                        />
                    )}
                </LemonField>

                <div className="flex items-center gap-2">
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        form="agent-application-settings"
                        loading={isSettingsSubmitting}
                    >
                        Save changes
                    </LemonButton>
                    <LemonButton type="secondary" onClick={() => resetSettings()}>
                        Discard
                    </LemonButton>
                </div>
            </div>
        </Form>
    )
}
