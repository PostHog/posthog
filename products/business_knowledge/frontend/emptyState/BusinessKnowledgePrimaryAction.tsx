import { useActions } from 'kea'

import { IconPlusSmall } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { CreateKnowledgeSourceModal } from '../components/CreateKnowledgeSourceModal'
import { REFRESH_INTERVAL_OPTIONS, businessKnowledgeLogic } from '../scenes/businessKnowledgeLogic'

/**
 * "Add source" for the business knowledge empty state. The scene normally renders
 * the create modal, and the gate replaces the scene, so the empty state renders
 * the modal itself or the button would open nothing.
 */
export function BusinessKnowledgePrimaryAction(): JSX.Element {
    const { openCreateModal } = useActions(businessKnowledgeLogic)

    return (
        <>
            <LemonButton
                type="primary"
                className="self-start"
                icon={<IconPlusSmall />}
                onClick={() => openCreateModal()}
                data-attr="add-knowledge-source-button"
            >
                Add your first source
            </LemonButton>
            <CreateKnowledgeSourceModal refreshIntervalOptions={REFRESH_INTERVAL_OPTIONS} />
        </>
    )
}
