import { LemonButton, LemonCheckbox, LemonModal, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { Group } from '~/types'

import { groupDeleteModalLogic } from './groupDeleteModalLogic'

export function GroupDeleteModal(): JSX.Element | null {
    const { groupDeleteModal } = useValues(groupDeleteModalLogic)
    const [isDeletionConfirmed, setIsDeletionConfirmed] = useState(false)
    const { deleteGroup, showGroupDeleteModal } = useActions(groupDeleteModalLogic)

    return (
        <LemonModal
            isOpen={!!groupDeleteModal}
            onClose={() => showGroupDeleteModal(null)}
            title={`Are you sure you want to delete "${groupDeleteModal?.group_key}"?`}
            description={
                <>
                    <p>This action cannot be undone.</p>
                    <p>
                        If you opt to delete the group and its corresponding events, the events will not be immediately
                        removed. Instead these events will be deleted on a set schedule during non-peak usage times.{' '}
                        <Link to="https://posthog.com/docs/privacy/data-deletion" target="_blank" className="font-bold">
                            Learn more
                        </Link>
                    </p>
                    <LemonCheckbox
                        onChange={(value) => setIsDeletionConfirmed(value)}
                        checked={isDeletionConfirmed}
                        className="mt-3"
                        label="I understand that this action cannot be undone."
                    />
                </>
            }
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={() => showGroupDeleteModal(null)}
                        data-attr="delete-group-cancel"
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        status="danger"
                        onClick={() => deleteGroup(groupDeleteModal as Group)}
                        disabled={!isDeletionConfirmed}
                        data-attr="delete-group-no-events"
                    >
                        Delete group
                    </LemonButton>
                </>
            }
        />
    )
}
