import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonInput } from '@posthog/lemon-ui'

import { DOMAIN_REGEX } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

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
        <LemonModal
            onClose={handleClose}
            isOpen={addModalShown}
            title="Add authentication domain"
            footer={
                <LemonButton
                    type="primary"
                    disabled={newDomain === '' || (submitted && errored) || verifiedDomainsLoading}
                    onClick={handleSubmit}
                >
                    Add domain
                </LemonButton>
            }
        >
            <LemonInput
                placeholder="posthog.com"
                autoFocus
                value={newDomain}
                onChange={setNewDomain}
                onPressEnter={handleSubmit}
            />
            {submitted && errored && (
                <span className="text-danger text-xs">
                    Please enter a valid domain or subdomain name (e.g. my.posthog.com)
                </span>
            )}
        </LemonModal>
    )
}
