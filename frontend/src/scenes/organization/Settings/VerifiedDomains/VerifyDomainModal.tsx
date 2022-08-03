import { Input } from 'antd'
import { useActions, useValues } from 'kea'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonModal } from 'lib/components/LemonModal/LemonModal'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import React from 'react'
import { verifiedDomainsLogic } from './verifiedDomainsLogic'

export function VerifyDomainModal(): JSX.Element {
    const { domainBeingVerified, updatingDomainLoading } = useValues(verifiedDomainsLogic)
    const { setVerifyModal, verifyDomain } = useActions(verifiedDomainsLogic)
    const challengeName = `_posthog-challenge.${domainBeingVerified?.domain}.`
    return (
        <LemonModal visible={!!domainBeingVerified} onCancel={() => setVerifyModal(null)}>
            <section>
                <h5>Verify your domain</h5>
                <LemonTag>{domainBeingVerified?.domain || ''}</LemonTag>
                <p className="text-muted-alt">To verify your domain, you need to add a record to your DNS zone.</p>

                <div>
                    <ol>
                        <li>Sign in to your DNS provider.</li>
                        <li>
                            Add the following <b>TXT</b> record.
                            <div className="my-4">
                                <div className="input-set">
                                    <label htmlFor="record-name">Name</label>
                                    <div className="flex items-center">
                                        <Input disabled value={challengeName} name="record-name" />
                                        <CopyToClipboardInline
                                            explicitValue={challengeName}
                                            style={{ marginLeft: 4 }}
                                        />
                                    </div>
                                </div>
                                <div className="input-set">
                                    <label htmlFor="record-value">Value or content</label>
                                    <div className="flex items-center">
                                        <Input
                                            disabled
                                            value={domainBeingVerified?.verification_challenge}
                                            name="record-value"
                                        />
                                        <CopyToClipboardInline
                                            explicitValue={domainBeingVerified?.verification_challenge}
                                            style={{ marginLeft: 4 }}
                                        />
                                    </div>
                                </div>
                                <div className="input-set">
                                    <label htmlFor="record-value">TTL</label>
                                    <div className="flex items-center">
                                        <Input disabled value="Default or 3600" name="record-value" />
                                        <CopyToClipboardInline explicitValue="3600" style={{ marginLeft: 4 }} />
                                    </div>
                                </div>
                            </div>
                        </li>
                        <li>Press verify below.</li>
                    </ol>
                </div>
                <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                    <LemonButton onClick={() => setVerifyModal(null)} style={{ marginRight: 8 }}>
                        Verify later
                    </LemonButton>
                    <LemonButton type="primary" disabled={updatingDomainLoading} onClick={verifyDomain}>
                        Verify
                    </LemonButton>
                </div>
            </section>
        </LemonModal>
    )
}
