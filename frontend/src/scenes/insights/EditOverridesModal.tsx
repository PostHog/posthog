import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { InsightLogicProps } from '~/types'

import { insightLogic } from './insightLogic'
import { insightSceneLogic } from './insightSceneLogic'

interface EditOverridesModalProps {
    isOpen: boolean
    closeModal: () => void
    insightProps: InsightLogicProps
}

export function EditOverridesModal({ isOpen, closeModal, insightProps }: EditOverridesModalProps): JSX.Element {
    const { insight, query } = useValues(insightLogic(insightProps))

    const { location, currentLocation } = useValues(router)
    const { push } = useActions(router)

    return (
        <LemonModal
            onClose={closeModal}
            isOpen={isOpen}
            title="Edit insight"
            maxWidth="40rem"
            footer={
                <div className="flex justify-between w-full">
                    <div>
                        <LemonButton type="secondary" onClick={closeModal}>
                            Cancel
                        </LemonButton>
                    </div>
                    <div className="flex gap-2">
                        <LemonButton
                            type="secondary"
                            onClick={() => {
                                // we whould always have a short_id when overrides are present
                                if (insight.short_id) {
                                    push(
                                        // :FIXME: This should work, but doesn't due to a race condition in insightsSceneLogic.
                                        // What I _think_ is happening roughly: urlToAction gets called with the query, and calls updateQuery.
                                        // Then setSceneState gets executed and calls the reloadInsightLogic listener. This then calls loadInsight,
                                        // but the overrides are empty as the url doesn't have them any more. Now the query doesn't have the overrides as
                                        // well.
                                        urls.insightEdit(
                                            insight.short_id,
                                            currentLocation.searchParams.dashboard,
                                            query
                                        )
                                    )
                                    closeModal()
                                }
                            }}
                        >
                            Edit with overrides
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                // we whould always have a short_id when overrides are present
                                if (insight.short_id) {
                                    push(urls.insightEdit(insight.short_id, currentLocation.searchParams.dashboard))
                                    closeModal()
                                }
                            }}
                        >
                            Edit without overrides
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <p>
                You are viewing the insight with <b>filter/variable overrides</b>. Editing and then saving, will also{' '}
                <b>save the overrides onto the insight</b>.
            </p>
            <p>Please choose how you would like to continue.</p>
        </LemonModal>
    )
}
