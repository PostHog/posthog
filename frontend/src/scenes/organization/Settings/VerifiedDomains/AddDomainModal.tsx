import { Input } from 'antd'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonModal } from 'lib/components/LemonModal/LemonModal'
import { DOMAIN_REGEX } from 'lib/constants'
import React, { useState } from 'react'
import { verifiedDomainsLogic } from './verifiedDomainsLogic'

export function AddDomainModal(): JSX.Element {
    const { addModalShown, verifiedDomainsLoading } = useValues(verifiedDomainsLogic)
    const { setAddModalShown, addVerifiedDomain } = useActions(verifiedDomainsLogic)
    const [newDomain, setNewDomain] = useState('')
    const [submitted, setSubmitted] = useState(false)

    const errored = !newDomain || !newDomain.match(DOMAIN_REGEX)

    const clean = (): void => {
        setNewDomain('')
        setSubmitted(false)
    }

    const handleClose = (): void => {
        setAddModalShown(false)
        clean()
    }

    const handleSubmit = (): void => {
        setSubmitted(true)
        if (!errored) {
            addVerifiedDomain(newDomain)
            clean()
        }
    }

    return (
        <LemonModal onCancel={handleClose} visible={addModalShown} destroyOnClose>
            <section>
                <h5>Add authentication domain</h5>

                <Input
                    placeholder="posthog.com"
                    autoFocus
                    value={newDomain}
                    onChange={(e) => setNewDomain(e.target.value)}
                    onPressEnter={handleSubmit}
                />
                {submitted && errored && (
                    <span className="text-danger text-xs">
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
