import { useActions } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonInput, LemonModal, Link } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

export function CreateOrganizationModal({
    isVisible,
    onClose,
    inline = false,
}: {
    isVisible: boolean
    onClose?: () => void
    inline?: boolean
}): JSX.Element {
    const { createOrganization } = useActions(organizationLogic)
    const [name, setName] = useState<string>('')

    const closeModal: () => void = () => {
        if (onClose) {
            onClose()
            if (name) {
                setName('')
            }
        }
    }
    const handleSubmit = (): void => {
        createOrganization(name)
        closeModal()
    }

    return (
        <LemonModal
            width={440}
            title="Create an organization"
            description={
                <p>
                    Organizations gather people building together.
                    <br />
                    <Link to="https://posthog.com/docs/user-guides/organizations-and-projects" target="_blank">
                        Learn more in PostHog docs.
                    </Link>
                </p>
            }
            footer={
                <>
                    {onClose && (
                        <LemonButton type="secondary" onClick={() => onClose()}>
                            Cancel
                        </LemonButton>
                    )}
                    <LemonButton
                        type="primary"
                        onClick={() => handleSubmit()}
                        disabledReason={!name ? 'Think of a name!' : null}
                        data-attr="create-organization-ok"
                    >
                        Create organization
                    </LemonButton>
                    {inline && (
                        <div className="w-full text-right text-xs">
                            <span className="text-muted">
                                or <Link to={urls.settings('user')}>manage your account</Link>
                            </span>
                        </div>
                    )}
                </>
            }
            onClose={closeModal}
            isOpen={isVisible}
            inline={inline}
        >
            <LemonField.Pure label="Organization name">
                <LemonInput
                    placeholder="Acme Inc."
                    maxLength={64}
                    autoFocus
                    value={name}
                    onChange={(value) => setName(value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            handleSubmit()
                        }
                    }}
                    data-attr="organization-name-input"
                />
            </LemonField.Pure>
        </LemonModal>
    )
}
