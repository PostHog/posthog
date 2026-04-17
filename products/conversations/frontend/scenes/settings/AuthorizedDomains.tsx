import { useActions, useValues } from 'kea'

import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { Link } from 'lib/lemon-ui/Link'

import { supportSettingsLogic } from './supportSettingsLogic'

export function AuthorizedDomains(): JSX.Element {
    const { conversationsDomains, isAddingDomain, editingDomainIndex, domainInputValue } =
        useValues(supportSettingsLogic)
    const { setDomainInputValue, saveDomain, removeDomain, startEditDomain, cancelDomainEdit } =
        useActions(supportSettingsLogic)

    return (
        <div className="flex flex-col gap-2">
            {conversationsDomains.length === 0 && !isAddingDomain && (
                <div className="border rounded p-4 text-secondary">
                    <p className="mb-2">
                        <span className="font-bold">No domains configured.</span>
                        <br />
                        The widget will show on all domains. Add domains to limit where it appears.
                    </p>
                    <p className="mb-2">
                        <span className="font-bold">Ticket recovery is disabled until a domain is added.</span>{' '}
                        Recovering tickets by email requires at least one authorized domain so the recovery link can
                        only point to a site you control.
                    </p>
                    <p className="mb-0">
                        For logged-in users we recommend{' '}
                        <Link
                            to="https://posthog.com/docs/support/widget#identity-verification"
                            target="_blank"
                            targetBlankIcon
                        >
                            identity verification
                        </Link>{' '}
                        instead — tickets persist across browsers and devices automatically without relying on email
                        recovery.
                    </p>
                </div>
            )}

            {(isAddingDomain || editingDomainIndex !== null) && (
                <div className="border rounded p-2 bg-surface-primary">
                    <div className="gap-2">
                        <LemonInput
                            autoFocus
                            value={domainInputValue}
                            onChange={setDomainInputValue}
                            placeholder="https://example.com or https://*.example.com"
                            fullWidth
                            onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                    saveDomain(domainInputValue, editingDomainIndex)
                                } else if (e.key === 'Escape') {
                                    cancelDomainEdit()
                                }
                            }}
                        />
                        <div className="flex gap-2 mt-2">
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={() => saveDomain(domainInputValue, editingDomainIndex)}
                                disabledReason={!domainInputValue.trim() ? 'Enter a domain' : undefined}
                            >
                                Save
                            </LemonButton>
                            <LemonButton type="secondary" size="small" onClick={cancelDomainEdit}>
                                Cancel
                            </LemonButton>
                        </div>
                    </div>
                </div>
            )}

            {conversationsDomains.map((domain: string, index: number) =>
                editingDomainIndex === index ? null : (
                    <div key={index} className="border rounded flex items-center p-2 pl-4 bg-surface-primary">
                        <span title={domain} className="flex-1 truncate">
                            {domain}
                        </span>
                        <div className="flex gap-1 shrink-0">
                            <LemonButton
                                icon={<IconPencil />}
                                onClick={() => startEditDomain(index)}
                                tooltip="Edit"
                                size="small"
                            />
                            <LemonButton
                                icon={<IconTrash />}
                                tooltip="Remove domain"
                                size="small"
                                onClick={() => {
                                    LemonDialog.open({
                                        title: <>Remove {domain}?</>,
                                        description: 'Are you sure you want to remove this domain?',
                                        primaryButton: {
                                            status: 'danger',
                                            children: 'Remove',
                                            onClick: () => removeDomain(index),
                                        },
                                        secondaryButton: {
                                            children: 'Cancel',
                                        },
                                    })
                                }}
                            />
                        </div>
                    </div>
                )
            )}
        </div>
    )
}
