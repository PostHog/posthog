import posthog from 'posthog-js'

import { LemonDialog, LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { matchesConfirmationText } from 'lib/utils/confirmationText'
import { pluralize } from 'lib/utils/strings'

import type { OrganizationPersonalAPIKeyApi } from 'products/platform_features/frontend/generated/api.schemas'

import type { BulkKeySummary, KeyAction, KeyActionTarget } from './organizationPersonalAPIKeysLogic'

const ROLL_ALL_PHRASE = 'roll all keys'
const REVOKE_ALL_PHRASE = 'revoke all keys'

function captureDialogOpened(action: KeyAction, target: KeyActionTarget): void {
    posthog.capture('organization personal api key action dialog opened', { action, target })
}

function agree(count: number, singular: string, plural: string): string {
    return count === 1 ? singular : plural
}

function keyName(key: OrganizationPersonalAPIKeyApi, owner: string): JSX.Element {
    return (
        <>
            The key <span className="font-mono">{key.mask_value}</span> owned by <strong>{owner}</strong>
        </>
    )
}

export function openRollKeyDialog(key: OrganizationPersonalAPIKeyApi, owner: string, onConfirm: () => void): void {
    captureDialogOpened('roll', 'single')
    LemonDialog.open({
        maxWidth: 480,
        title: 'Roll personal API key?',
        description: (
            <>
                <p>
                    {keyName(key, owner)} gets a new secret that nobody sees. It keeps its scopes and settings, but
                    stops working until the owner rolls it again in their own settings.
                </p>
                {key.reaches_other_organizations ? (
                    <p>This key also works in other organizations, so it stops working there too.</p>
                ) : null}
                <p>The owner gets an email about this change.</p>
            </>
        ),
        primaryButton: {
            children: 'Roll key',
            status: 'danger',
            onClick: onConfirm,
            'data-attr': 'organization-personal-api-key-roll-confirm',
        },
        secondaryButton: { children: 'Cancel' },
    })
}

export function openRevokeKeyDialog(key: OrganizationPersonalAPIKeyApi, owner: string, onConfirm: () => void): void {
    captureDialogOpened('revoke', 'single')
    LemonDialog.open({
        maxWidth: 480,
        title: 'Revoke personal API key?',
        description: (
            <>
                {key.reaches_other_organizations ? (
                    <p>
                        {keyName(key, owner)} also works in other organizations. Revoking it removes its access to this
                        organization only. It keeps working in the other organizations.
                    </p>
                ) : (
                    <p>
                        {keyName(key, owner)} works only in this organization, so revoking it deletes the key. Anything
                        that uses it stops working.
                    </p>
                )}
                <p>The owner gets an email about this change.</p>
            </>
        ),
        primaryButton: {
            children: 'Revoke key',
            status: 'danger',
            onClick: onConfirm,
            'data-attr': 'organization-personal-api-key-revoke-confirm',
        },
        secondaryButton: { children: 'Cancel' },
    })
}

interface BulkDialogOptions {
    action: KeyAction
    title: string
    description: string
    counts: (string | null)[]
    phrase: string
    confirmationDataAttr: string
    submitLabel: string
    onConfirm: () => void
}

function openBulkKeyActionDialog({
    action,
    title,
    description,
    counts,
    phrase,
    confirmationDataAttr,
    submitLabel,
    onConfirm,
}: BulkDialogOptions): void {
    captureDialogOpened(action, 'all')
    const typeToConfirm = `Type "${phrase}" to confirm`
    LemonDialog.openForm({
        dialogKey: `organization-personal-api-keys-${action}-all`,
        maxWidth: 480,
        title,
        description,
        initialValues: { confirmation: '' },
        content: (
            <div className="space-y-4">
                <ul className="list-disc pl-5 space-y-1">
                    {counts
                        .filter((line): line is string => line !== null)
                        .map((line) => (
                            <li key={line}>{line}</li>
                        ))}
                </ul>
                <LemonField name="confirmation" label={typeToConfirm}>
                    <LemonInput autoFocus data-attr={confirmationDataAttr} />
                </LemonField>
            </div>
        ),
        errors: {
            confirmation: (value?: string) =>
                matchesConfirmationText(value ?? '', phrase) ? undefined : typeToConfirm,
        },
        primaryButtonProps: { status: 'danger', children: submitLabel },
        onSubmit: onConfirm,
    })
}

function ownedByMeLine(ownedByMe: number): string | null {
    return ownedByMe ? `${pluralize(ownedByMe, 'key')} ${agree(ownedByMe, 'belongs', 'belong')} to you.` : null
}

export function openRollAllKeysDialog(
    { total, alsoInOtherOrganizations, ownedByMe }: BulkKeySummary,
    onConfirm: () => void
): void {
    openBulkKeyActionDialog({
        action: 'roll',
        title: 'Roll all personal API keys?',
        description:
            'Every personal API key with access to this organization gets a new secret that nobody sees. Each key keeps its scopes and settings, but stops working until its owner rolls it again in their own settings. Each owner gets an email about this change.',
        counts: [
            `This rolls ${pluralize(total, 'key')}.`,
            alsoInOtherOrganizations
                ? `${pluralize(alsoInOtherOrganizations, 'key')} also ${agree(alsoInOtherOrganizations, 'works', 'work')} in other organizations and ${agree(alsoInOtherOrganizations, 'stops', 'stop')} working there too.`
                : null,
            ownedByMeLine(ownedByMe),
        ],
        phrase: ROLL_ALL_PHRASE,
        confirmationDataAttr: 'organization-personal-api-keys-roll-all-confirmation-input',
        submitLabel: 'Roll all keys',
        onConfirm,
    })
}

export function openRevokeAllKeysDialog(
    { total, alsoInOtherOrganizations, ownedByMe }: BulkKeySummary,
    onConfirm: () => void
): void {
    const onlyInThisOrganization = total - alsoInOtherOrganizations
    openBulkKeyActionDialog({
        action: 'revoke',
        title: 'Revoke all personal API keys?',
        description:
            'Every personal API key with access to this organization loses that access. A key that works only in this organization gets deleted. A key that also works in other organizations keeps working there. Each owner gets an email about this change.',
        counts: [
            `This revokes ${pluralize(total, 'key')}.`,
            onlyInThisOrganization
                ? `${pluralize(onlyInThisOrganization, 'key')} ${agree(onlyInThisOrganization, 'works', 'work')} only in this organization and ${agree(onlyInThisOrganization, 'gets', 'get')} deleted.`
                : null,
            alsoInOtherOrganizations
                ? `${pluralize(alsoInOtherOrganizations, 'key')} also ${agree(alsoInOtherOrganizations, 'works', 'work')} in other organizations and ${agree(alsoInOtherOrganizations, 'keeps', 'keep')} working there.`
                : null,
            ownedByMeLine(ownedByMe),
        ],
        phrase: REVOKE_ALL_PHRASE,
        confirmationDataAttr: 'organization-personal-api-keys-revoke-all-confirmation-input',
        submitLabel: 'Revoke all keys',
        onConfirm,
    })
}
