import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPhone, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonSkeleton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { SMSIntegrationItemApi } from '~/generated/core/api.schemas'

import { smsIntegrationLogic } from './smsIntegrationLogic'

function PhoneNumberRow({ integration }: { integration: SMSIntegrationItemApi }): JSX.Element {
    const { removePhone } = useActions(smsIntegrationLogic)

    const handleRemove = (): void => {
        LemonDialog.open({
            title: `Remove ${integration.phone_number}?`,
            description: 'PostHog will stop replying to messages from this phone number.',
            primaryButton: {
                children: 'Remove',
                status: 'danger',
                onClick: () => removePhone(integration.phone_number),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div className="flex items-center gap-4 px-4 py-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border bg-surface-secondary text-2xl">
                <IconPhone />
            </div>
            <div className="min-w-0 flex-1">
                <div className="font-semibold">{integration.phone_number}</div>
                <div className="mt-0.5 text-xs text-secondary">
                    Verified <TZLabel time={integration.created_at} className="align-baseline" />
                </div>
            </div>
            <LemonButton
                size="small"
                type="secondary"
                status="danger"
                icon={<IconTrash />}
                onClick={handleRemove}
                tooltip="Remove this phone number"
            />
        </div>
    )
}

function VerificationForm(): JSX.Element {
    const { pendingPhoneNumber, startingVerification, verifyingCode } = useValues(smsIntegrationLogic)
    const { startVerification, verifyCode, cancelVerification } = useActions(smsIntegrationLogic)
    const [phoneInput, setPhoneInput] = useState('')
    const [codeInput, setCodeInput] = useState('')

    if (pendingPhoneNumber) {
        return (
            <div className="flex flex-col gap-2 px-4 py-3">
                <div className="text-sm">
                    Enter the 6-digit code we sent to <strong>{pendingPhoneNumber}</strong>.
                </div>
                <div className="flex gap-2">
                    <LemonInput
                        value={codeInput}
                        onChange={setCodeInput}
                        placeholder="123456"
                        autoFocus
                        maxLength={6}
                        className="max-w-32"
                    />
                    <LemonButton
                        type="primary"
                        loading={verifyingCode}
                        disabledReason={codeInput.length < 6 ? 'Enter the 6-digit code' : null}
                        onClick={() => verifyCode(pendingPhoneNumber, codeInput)}
                    >
                        Verify
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        onClick={() => {
                            cancelVerification()
                            setCodeInput('')
                        }}
                    >
                        Cancel
                    </LemonButton>
                </div>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2 px-4 py-3">
            <div className="flex gap-2">
                <LemonInput
                    value={phoneInput}
                    onChange={setPhoneInput}
                    placeholder="+14155552671"
                    autoFocus
                    className="max-w-56"
                />
                <LemonButton
                    type="primary"
                    loading={startingVerification}
                    disabledReason={phoneInput.trim().length === 0 ? 'Enter a phone number' : null}
                    onClick={() => startVerification(phoneInput.trim())}
                >
                    Send code
                </LemonButton>
            </div>
            <div className="text-xs text-secondary">
                Use international (E.164) format, e.g. +14155552671. We'll text a 6-digit code to confirm you own the
                number.
            </div>
        </div>
    )
}

export function SMSIntegrationSettings(): JSX.Element {
    const { sms, smsLoading } = useValues(smsIntegrationLogic)

    if (smsLoading && sms.length === 0) {
        return (
            <div className="deprecated-space-y-2">
                <LemonSkeleton className="h-16 w-full" />
            </div>
        )
    }

    return (
        <div className="deprecated-space-y-3">
            <div className="divide-y rounded border bg-surface-primary">
                {sms.length === 0 ? (
                    <div className="px-4 py-6 text-center text-sm text-secondary">
                        <IconPhone className="text-3xl mb-2 opacity-40" />
                        <p className="mb-1">No phone number connected yet</p>
                        <p className="text-xs text-muted text-balance">
                            Verify a phone number to get text replies from PostHog Code.
                        </p>
                    </div>
                ) : (
                    sms.map((integration) => <PhoneNumberRow key={integration.id} integration={integration} />)
                )}
                {sms.length === 0 && <VerificationForm />}
            </div>
        </div>
    )
}
