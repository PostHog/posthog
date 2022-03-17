import { Input } from 'antd'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonModal } from 'lib/components/LemonModal/LemonModal'
import React, { useState } from 'react'
import { verifiedDomainsLogic } from './verifiedDomainsLogic'

const DOMAIN_REGEX = /^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$/

export function AddDomainModal(): JSX.Element {
    const { addModalShown, verifiedDomainsLoading } = useValues(verifiedDomainsLogic)
    const { setModalShown, addVerifiedDomain } = useActions(verifiedDomainsLogic)
    const [newDomain, setNewDomain] = useState('')
    const [submitted, setSubmitted] = useState(false)

    const errored = !newDomain || !newDomain.match(DOMAIN_REGEX)

    const handleSubmit = (): void => {
        setSubmitted(true)
        if (!errored) {
            addVerifiedDomain(newDomain)
        }
    }

    return (
        <LemonModal onCancel={() => setModalShown(false)} visible={addModalShown}>
            <section>
                <h5>Add verified domain</h5>

                <Input
                    placeholder="posthog.com"
                    autoFocus
                    value={newDomain}
                    onChange={(e) => setNewDomain(e.target.value)}
                    onPressEnter={handleSubmit}
                />
                {submitted && errored && (
                    <span className="text-danger text-small">
                        Please enter a valid domain or subdomain name (e.g. my.posthog.com)
                    </span>
                )}
                <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                    <LemonButton
                        type="primary"
                        disabled={newDomain === '' || (submitted && errored) || verifiedDomainsLoading}
                        onClick={handleSubmit}
                    >
                        Add domain
                    </LemonButton>
                </div>
            </section>
        </LemonModal>
    )
}
