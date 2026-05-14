import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useState } from 'react'

import { IconBolt, IconCheckCircle, IconLock, IconShieldLock, IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { agentApplicationLogic, type RequiredSecret } from '../agentApplicationLogic'

interface SecretFieldState {
    [key: string]: string
}

function SecretsPanel(): JSX.Element {
    const { agentConfig, existingEnvKeys } = useValues(agentApplicationLogic)
    const { saveSecrets } = useActions(agentApplicationLogic)
    const [fields, setFields] = useState<SecretFieldState>({})
    const [saving, setSaving] = useState(false)

    const secrets: RequiredSecret[] = agentConfig?.required_secrets ?? []

    if (secrets.length === 0) {
        return (
            <div className="as-mono text-xs" style={{ color: 'var(--as-text-dim)' }}>
                // no secrets required by this agent's tools
            </div>
        )
    }

    const handleSave = (): void => {
        const changed: Record<string, string> = {}
        for (const [key, value] of Object.entries(fields)) {
            if (value && value.trim()) {
                changed[key] = value
            }
        }
        if (Object.keys(changed).length === 0) {
            return
        }
        setSaving(true)
        saveSecrets(changed)
        setTimeout(() => {
            setSaving(false)
            setFields({})
        }, 1000)
    }

    const hasChanges = Object.values(fields).some((v) => v && v.trim())

    return (
        <div className="flex flex-col gap-4">
            <div className="as-label flex items-center gap-2">
                <IconShieldLock style={{ color: 'var(--as-live)', width: 14, height: 14 }} />▌ Required secrets
            </div>
            <p className="as-mono text-xs my-0" style={{ color: 'var(--as-text-dim)' }}>
                // these keys are declared by the agent's tools · set them here or via <code>PATCH /env/</code>
            </p>

            <div className="flex flex-col gap-3">
                {secrets.map((secret) => {
                    const isSet = existingEnvKeys.has(secret.key)
                    const fieldValue = fields[secret.key] ?? ''
                    return (
                        <div
                            key={secret.key}
                            className="as-tile"
                            style={{
                                display: 'flex',
                                flexDirection: 'column',
                                gap: 8,
                                borderColor: !isSet ? 'rgba(251, 191, 36, 0.3)' : undefined,
                            }}
                        >
                            <div className="flex items-center justify-between gap-2">
                                <div className="flex items-center gap-2">
                                    <IconLock
                                        style={{
                                            color: isSet ? 'var(--as-live)' : 'var(--as-warning)',
                                            width: 12,
                                            height: 12,
                                        }}
                                    />
                                    <code
                                        className="as-mono"
                                        style={{
                                            color: 'var(--as-text)',
                                            fontWeight: 500,
                                            fontSize: 13,
                                        }}
                                    >
                                        {secret.key}
                                    </code>
                                    {isSet ? (
                                        <span
                                            className="as-pill as-pill-live"
                                            style={{ fontSize: 8, padding: '1px 5px' }}
                                        >
                                            <IconCheckCircle style={{ width: 8, height: 8 }} />
                                            set
                                        </span>
                                    ) : (
                                        <span
                                            className="as-pill as-pill-warning"
                                            style={{ fontSize: 8, padding: '1px 5px' }}
                                        >
                                            <IconWarning style={{ width: 8, height: 8 }} />
                                            missing
                                        </span>
                                    )}
                                </div>
                                <div className="flex items-center gap-1">
                                    <IconBolt style={{ color: 'var(--as-text-dim)', width: 10, height: 10 }} />
                                    <span className="as-mono text-xs" style={{ color: 'var(--as-text-dim)' }}>
                                        {secret.tool}
                                    </span>
                                </div>
                            </div>
                            {secret.description && (
                                <span className="as-mono text-xs" style={{ color: 'var(--as-text-muted)' }}>
                                    {secret.description}
                                </span>
                            )}
                            <input
                                className="as-input"
                                type="password"
                                value={fieldValue}
                                onChange={(e) => setFields({ ...fields, [secret.key]: e.target.value })}
                                placeholder={isSet ? '********' : 'enter value…'}
                                autoComplete="off"
                            />
                        </div>
                    )
                })}
            </div>

            <div className="flex items-center gap-2">
                <LemonButton
                    type="primary"
                    size="small"
                    loading={saving}
                    disabledReason={!hasChanges ? 'no changes to save' : undefined}
                    onClick={handleSave}
                >
                    Save secrets
                </LemonButton>
                {hasChanges && (
                    <span className="as-mono text-xs" style={{ color: 'var(--as-text-muted)' }}>
                        {Object.values(fields).filter((v) => v && v.trim()).length} key
                        {Object.values(fields).filter((v) => v && v.trim()).length === 1 ? '' : 's'} changed
                    </span>
                )}
            </div>
        </div>
    )
}

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
        <div className="flex flex-col gap-8">
            {/* Secrets section — per-key from required_secrets */}
            <SecretsPanel />

            <div className="as-divider" />

            {/* App details form */}
            <Form
                id="agent-application-settings"
                formKey="settings"
                logic={agentApplicationLogic}
                enableFormOnSubmit
                className="grid grid-cols-1 lg:grid-cols-5 gap-8"
            >
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

                <div className="lg:col-span-3" />
            </Form>
        </div>
    )
}
