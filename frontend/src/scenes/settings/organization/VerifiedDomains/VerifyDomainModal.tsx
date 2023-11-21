import { useActions, useValues } from 'kea'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { PureField } from 'lib/forms/Field'
import { verifiedDomainsLogic } from './verifiedDomainsLogic'

export function VerifyDomainModal(): JSX.Element {
    const { domainBeingVerified, updatingDomainLoading } = useValues(verifiedDomainsLogic)
    const { setVerifyModal, verifyDomain } = useActions(verifiedDomainsLogic)
    const challengeName = `_posthog-challenge.${domainBeingVerified?.domain}.`

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
                        <div className="my-4 space-y-2">
                            <PureField label="Name">
                                <div className="flex items-center gap-2">
                                    <div className="border rounded p-2 h-10 flex-1">{challengeName}</div>
                                    <CopyToClipboardInline explicitValue={challengeName} />
                                </div>
                            </PureField>

                            <PureField label="Value or content">
                                <div className="flex items-center gap-2">
                                    <div className="border rounded p-2 h-10 flex-1">
                                        {domainBeingVerified?.verification_challenge}
                                    </div>
                                    {domainBeingVerified && (
                                        <CopyToClipboardInline
                                            explicitValue={domainBeingVerified.verification_challenge}
                                        />
                                    )}
                                </div>
                            </PureField>
                            <PureField label="TTL">
                                <div className="flex items-center gap-2">
                                    <div className="border rounded p-2 h-10 flex-1">Default or 3600</div>
                                    <CopyToClipboardInline explicitValue="3600" />
                                </div>
                            </PureField>
                        </div>
                    </li>
                    <li>Press verify below.</li>
                </ol>
            </div>
        </LemonModal>
    )
}
