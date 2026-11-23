import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonInput } from '@posthog/lemon-ui'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldError,
    FieldLabel,
    Input,
} from '@posthog/quill'

import { DOMAIN_REGEX } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { verifiedDomainsLogic } from './verifiedDomainsLogic'

export function AddDomainModal(): JSX.Element {
    const { addModalShown, verifiedDomainsLoading } = useValues(verifiedDomainsLogic)
    const { hideAddDomainModal, addVerifiedDomain } = useActions(verifiedDomainsLogic)
    const [newDomain, setNewDomain] = useState('')
    const [submitted, setSubmitted] = useState(false)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const errored = !newDomain || !newDomain.match(DOMAIN_REGEX)

    const clean = (): void => {
        setNewDomain('')
        setSubmitted(false)
    }

    const handleClose = (): void => {
        hideAddDomainModal()
        clean()
    }

    const handleSubmit = (): void => {
        setSubmitted(true)
        if (!errored) {
            addVerifiedDomain(newDomain)
            clean()
        }
    }

    if (todayRailNav) {
        return (
            <Dialog open={addModalShown} onOpenChange={(open) => !open && handleClose()}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Add authentication domain</DialogTitle>
                    </DialogHeader>
                    <DialogBody>
                        <Field data-invalid={submitted && errored ? true : undefined}>
                            <FieldLabel htmlFor="add-authentication-domain" className="sr-only">
                                Domain
                            </FieldLabel>
                            <Input
                                id="add-authentication-domain"
                                placeholder="posthog.com"
                                autoFocus
                                value={newDomain}
                                onChange={(event) => setNewDomain(event.target.value)}
                                onKeyDown={(event) => event.key === 'Enter' && handleSubmit()}
                                aria-invalid={submitted && errored}
                            />
                            {submitted && errored && (
                                <FieldError>
                                    Please enter a valid domain or subdomain name (e.g. my.posthog.com)
                                </FieldError>
                            )}
                        </Field>
                    </DialogBody>
                    <DialogFooter>
                        <Button
                            variant="primary"
                            disabled={newDomain === '' || (submitted && errored) || verifiedDomainsLoading}
                            onClick={handleSubmit}
                        >
                            Add domain
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        )
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
