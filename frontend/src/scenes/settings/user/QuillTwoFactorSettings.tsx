import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconCheckCircle, IconInfo, IconWarning } from '@posthog/icons'
import {
    Badge,
    Button,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemTitle,
    Skeleton,
    Switch,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { twoFactorLogic } from 'scenes/authentication/two-factor-setup/twoFactorLogic'

import { QuillBackupCodesDialog } from './QuillBackupCodesDialog'
import { QuillDisable2FADialog } from './QuillDisable2FADialog'

function MethodInfo({ label, children }: { label: string; children: ReactNode }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger delay={0} render={<Button size="icon-xs" aria-label={label} />}>
                <IconInfo />
            </TooltipTrigger>
            <TooltipContent className="max-w-80">
                <div className="flex flex-col gap-2">{children}</div>
            </TooltipContent>
        </Tooltip>
    )
}

export function QuillTwoFactorSettings({
    onConfirmDisable2FA,
    onCopyBackupCodes,
    onTogglePasskeysFor2FA,
}: {
    onConfirmDisable2FA: () => void
    onCopyBackupCodes: () => void
    onTogglePasskeysFor2FA: () => void
}): JSX.Element {
    const { status, statusLoadFailed, isDisable2FAModalOpen } = useValues(twoFactorLogic)
    const { loadStatus, openTwoFactorSetupModal, toggleDisable2FAModal, toggleBackupCodesModal } =
        useActions(twoFactorLogic)

    if (!status) {
        return statusLoadFailed ? (
            <Item tone="destructive" size="sm">
                <ItemContent>
                    <ItemDescription>Couldn't load your 2FA settings.</ItemDescription>
                </ItemContent>
                <ItemActions>
                    <Button variant="outline" onClick={() => loadStatus()}>
                        Retry
                    </Button>
                </ItemActions>
            </Item>
        ) : (
            <div className="flex flex-col gap-2">
                <Skeleton className="h-6 w-40" />
                <Skeleton className="h-32 w-full" />
            </div>
        )
    }

    const hasTotp = status.has_totp
    const hasPasskeys = status.has_passkeys
    const passkeysEnabled = status.passkeys_enabled_for_2fa

    return (
        <div className="flex flex-col items-start gap-4">
            <QuillDisable2FADialog
                open={isDisable2FAModalOpen}
                onClose={() => toggleDisable2FAModal(false)}
                onConfirm={onConfirmDisable2FA}
            />
            <QuillBackupCodesDialog onCopyBackupCodes={onCopyBackupCodes} />

            {status.is_enabled ? (
                <Badge variant="success">
                    <IconCheckCircle />
                    2FA enabled
                </Badge>
            ) : (
                <Badge variant="warning">
                    <IconWarning />
                    2FA not enabled
                </Badge>
            )}

            <ItemGroup combined className="max-w-200">
                <Item variant="outline">
                    <ItemContent>
                        <ItemTitle>
                            Authenticator app
                            <MethodInfo label="About authenticator apps">
                                <p className="m-0">
                                    Use an authenticator app (like Google Authenticator, Authy, or 1Password) to
                                    generate time-based codes for 2FA.
                                </p>
                                <p className="m-0">
                                    When enabled, you'll be asked for a code from your authenticator app when signing
                                    in.
                                </p>
                            </MethodInfo>
                        </ItemTitle>
                        <ItemDescription>
                            {hasTotp
                                ? 'Authenticator app is set up and enabled for 2FA.'
                                : 'Set up an authenticator app to use time-based codes for 2FA.'}
                        </ItemDescription>
                    </ItemContent>
                    <ItemActions className="flex-wrap">
                        {hasTotp ? (
                            <>
                                <Button variant="outline" onClick={() => toggleBackupCodesModal(true)}>
                                    Backup codes
                                </Button>
                                <Button variant="destructive-outline" onClick={() => toggleDisable2FAModal(true)}>
                                    Disable
                                </Button>
                            </>
                        ) : (
                            <Button variant="primary" onClick={() => openTwoFactorSetupModal()}>
                                Setup
                            </Button>
                        )}
                    </ItemActions>
                </Item>

                <Item variant="outline">
                    <ItemContent>
                        <ItemTitle>
                            Passkeys
                            <MethodInfo label="About passkeys for 2FA">
                                <p className="m-0">
                                    Passkeys provide a secure, passwordless way to sign in and can be used for 2FA
                                    authentication.
                                </p>
                                <p className="m-0">
                                    {hasPasskeys
                                        ? 'You have passkeys set up. They are automatically used for 2FA when available.'
                                        : 'Add a passkey in the Passkeys settings to enable this method for 2FA.'}
                                </p>
                            </MethodInfo>
                        </ItemTitle>
                        <ItemDescription>
                            {hasPasskeys
                                ? passkeysEnabled
                                    ? 'Passkeys are enabled for 2FA. Manage your passkeys in the Passkeys settings.'
                                    : 'Passkeys are disabled for 2FA. Enable the switch above to use passkeys for 2FA.'
                                : 'No passkeys set up. Add a passkey to use this method for 2FA.'}
                        </ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Switch
                            checked={passkeysEnabled}
                            onCheckedChange={() => onTogglePasskeysFor2FA()}
                            aria-label={passkeysEnabled ? 'Disable passkeys for 2FA' : 'Enable passkeys for 2FA'}
                            disabledReason={
                                !hasPasskeys ? 'Add a passkey in Passkeys settings to enable this method' : undefined
                            }
                        />
                    </ItemActions>
                </Item>
            </ItemGroup>
        </div>
    )
}
