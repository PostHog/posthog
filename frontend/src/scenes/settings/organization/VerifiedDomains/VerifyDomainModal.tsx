import { useActions, useValues } from 'kea'

import {
    Badge,
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldLabel,
    Text,
} from '@posthog/quill'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'

import { verifiedDomainsLogic } from './verifiedDomainsLogic'

export function VerifyDomainModal(): JSX.Element {
    const { domainBeingVerified, updatingDomainLoading } = useValues(verifiedDomainsLogic)
    const { setVerifyModal, verifyDomain } = useActions(verifiedDomainsLogic)
    const challengeName = `_posthog-challenge.${domainBeingVerified?.domain}.`
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        const records = [
            { label: 'Name', display: challengeName, copy: challengeName },
            {
                label: 'Value or content',
                display: domainBeingVerified?.verification_challenge,
                copy: domainBeingVerified?.verification_challenge,
            },
            { label: 'TTL', display: 'Default or 3600', copy: '3600' },
        ]

        return (
            <Dialog open={!!domainBeingVerified} onOpenChange={(open) => !open && setVerifyModal(null)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Verify your domain</DialogTitle>
                        <DialogDescription render={<div className="flex flex-col items-start gap-2" />}>
                            <Badge className="uppercase">{domainBeingVerified?.domain || ''}</Badge>
                            <span>To verify your domain, you need to add a record to your DNS zone.</span>
                        </DialogDescription>
                    </DialogHeader>
                    <DialogBody>
                        <ol className="m-0 flex flex-col gap-2 pl-4">
                            <Text size="xs" render={<li />}>
                                Sign in to your DNS provider.
                            </Text>
                            <Text size="xs" render={<li className="flex flex-col gap-2" />}>
                                <span>
                                    Add the following <b>TXT</b> record.
                                </span>
                                {records.map(({ label, display, copy }) => (
                                    <Field key={label}>
                                        <FieldLabel>{label}</FieldLabel>
                                        <div className="flex items-center gap-2">
                                            <div className="flex-1 rounded-md border border-border p-2 font-mono break-all">
                                                {display}
                                            </div>
                                            {copy && <CopyToClipboardInline explicitValue={copy} selectable={true} />}
                                        </div>
                                    </Field>
                                ))}
                            </Text>
                            <Text size="xs" render={<li />}>
                                Press verify below.
                            </Text>
                        </ol>
                    </DialogBody>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setVerifyModal(null)}>
                            Verify later
                        </Button>
                        <Button variant="primary" disabled={updatingDomainLoading} onClick={verifyDomain}>
                            Verify
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        )
    }

    return (
        <LemonModal
            isOpen={!!domainBeingVerified}
            onClose={() => setVerifyModal(null)}
            title="Verify your domain"
            description={
                <>
                    <LemonTag className="uppercase">{domainBeingVerified?.domain || ''}</LemonTag>
                    <p>To verify your domain, you need to add a record to your DNS zone.</p>
                </>
            }
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => setVerifyModal(null)}>
                        Verify later
                    </LemonButton>
                    <LemonButton type="primary" disabled={updatingDomainLoading} onClick={verifyDomain}>
                        Verify
                    </LemonButton>
                </>
            }
        >
            <div>
                <ol>
                    <li>Sign in to your DNS provider.</li>
                    <li>
                        Add the following <b>TXT</b> record.
                        <div className="my-4 deprecated-space-y-2">
                            <LemonField.Pure label="Name">
                                <div className="flex items-center gap-2">
                                    <div className="border rounded p-2 h-10 flex-1">{challengeName}</div>
                                    <CopyToClipboardInline explicitValue={challengeName} selectable={true} />
                                </div>
                            </LemonField.Pure>

                            <LemonField.Pure label="Value or content">
                                <div className="flex items-center gap-2">
                                    <div className="border rounded p-2 h-10 flex-1">
                                        {domainBeingVerified?.verification_challenge}
                                    </div>
                                    {domainBeingVerified && (
                                        <CopyToClipboardInline
                                            explicitValue={domainBeingVerified.verification_challenge}
                                            selectable={true}
                                        />
                                    )}
                                </div>
                            </LemonField.Pure>
                            <LemonField.Pure label="TTL">
                                <div className="flex items-center gap-2">
                                    <div className="border rounded p-2 h-10 flex-1">Default or 3600</div>
                                    <CopyToClipboardInline explicitValue="3600" selectable={true} />
                                </div>
                            </LemonField.Pure>
                        </div>
                    </li>
                    <li>Press verify below.</li>
                </ol>
            </div>
        </LemonModal>
    )
}
