import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, Spinner } from '@posthog/lemon-ui'

import { ScoreDefinitionVersionLogicProps, scoreDefinitionVersionLogic } from './scoreDefinitionVersionLogic'

export function ScoreDefinitionVersionModal(props: ScoreDefinitionVersionLogicProps): JSX.Element {
    const logic = useMountedLogic(scoreDefinitionVersionLogic(props))
    const { currentDefinition, currentDefinitionLoading, submitting, error } = useValues(logic)
    const { submit, loadCurrentDefinition } = useActions(logic)

    return (
        <LemonModal
            isOpen
            title="Create new scorer version"
            onClose={props.onClose}
            closable={!submitting}
            maxWidth="32rem"
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={props.onClose}
                        disabledReason={submitting ? 'Creating a version' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submit}
                        loading={submitting}
                        disabledReason={
                            currentDefinitionLoading || !currentDefinition
                                ? 'Load the current version first'
                                : undefined
                        }
                    >
                        Create new version
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-3">
                <p>
                    Record a change to your external evaluator while keeping the scorer configuration exactly the same.
                    Use the new version ID for subsequent results.
                </p>
                {currentDefinitionLoading ? (
                    <Spinner />
                ) : currentDefinition ? (
                    <p>
                        <strong>{currentDefinition.name}</strong>
                        <span> will use the configuration from version {currentDefinition.current_version}.</span>
                    </p>
                ) : null}
                {error && <LemonBanner type="error">{error}</LemonBanner>}
                {!currentDefinition && !currentDefinitionLoading && (
                    <LemonButton onClick={() => loadCurrentDefinition()}>Try again</LemonButton>
                )}
            </div>
        </LemonModal>
    )
}
