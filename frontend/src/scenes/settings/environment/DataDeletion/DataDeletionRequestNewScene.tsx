import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCollapse, LemonInput, LemonLabel } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { SQLEditor } from 'scenes/data-warehouse/editor/SQLEditor'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'
import type { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import {
    DATA_DELETION_EDITOR_TAB_ID,
    DELETION_CONFIRMATION_TEXT,
    dataDeletionRequestNewLogic,
} from './dataDeletionRequestNewLogic'

const UUID_LIST_EXAMPLE = `SELECT arrayJoin([
    toUUID('0190a1b2-0000-7000-8000-000000000001'),
    toUUID('0190a1b2-0000-7000-8000-000000000002')
]) AS uuid`

export const scene: SceneExport = {
    component: DataDeletionRequestNewScene,
    logic: dataDeletionRequestNewLogic,
}

export function DataDeletionRequestNewScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const {
        currentPreview,
        previewLoading,
        previewError,
        queryIsEmpty,
        confirmationText,
        submitDisabledReason,
        createdRequestLoading,
        submitError,
    } = useValues(dataDeletionRequestNewLogic)
    const { previewQuery, setConfirmationText, submitRequest } = useActions(dataDeletionRequestNewLogic)

    if (!featureFlags[FEATURE_FLAGS.SELF_SERVICE_DATA_DELETION]) {
        return <NotFound object="page" />
    }

    return (
        <SceneContent className="pb-8">
            <SceneTitleSection
                name="New deletion request"
                description="Delete the events that a SQL query selects."
                resourceType={{ type: 'settings', forceIcon: <IconTrash /> }}
            />
            <LemonBanner type="warning">
                Deleted events cannot be recovered. PostHog reviews each request before anything is deleted, and
                deletion runs in the weekend deletion window after approval.
            </LemonBanner>
            <div className="flex flex-col gap-2">
                <p className="mb-0">
                    Write a query that returns one column of event UUIDs. Run it to check the rows, then check how many
                    events it matches. PostHog selects the matching events once, when it processes the request, so
                    events captured after that are not deleted.
                </p>
                <LemonCollapse
                    panels={[
                        {
                            key: 'uuid-list',
                            header: 'Delete a list of event UUIDs',
                            content: (
                                <div className="flex flex-col gap-2">
                                    <p className="mb-0">
                                        List the UUIDs in the query. A long list may exceed the query size limit, so
                                        split it into several requests.
                                    </p>
                                    <CodeSnippet language={Language.SQL}>{UUID_LIST_EXAMPLE}</CodeSnippet>
                                </div>
                            ),
                        },
                    ]}
                />
            </div>
            {/* Fixed height, because the embedded editor fills its container and has no height of its own */}
            <div className="h-160 border rounded overflow-hidden flex flex-col">
                <SQLEditor
                    tabId={DATA_DELETION_EDITOR_TAB_ID}
                    mode={SQLEditorMode.Embedded}
                    defaultShowDatabaseTree={false}
                    singleStatement
                    hideAgentHints
                    hideAiTools
                    hideVariables
                    hideFilters
                />
            </div>
            <div className="flex flex-col gap-2">
                <LemonButton
                    type="secondary"
                    className="self-start"
                    onClick={() => previewQuery()}
                    loading={previewLoading}
                    disabledReason={queryIsEmpty ? 'Write a query first' : undefined}
                    data-attr="data-deletion-check-matching-events"
                >
                    Check matching events
                </LemonButton>
                {previewError ? (
                    <LemonBanner type="error">{previewError}</LemonBanner>
                ) : currentPreview ? (
                    <p className="mb-0">
                        <span>This query matches </span>
                        <strong translate="no">{humanFriendlyNumber(currentPreview.count)}</strong>
                        <span> {currentPreview.count === 1 ? 'event' : 'events'}.</span>
                    </p>
                ) : null}
            </div>
            {currentPreview && currentPreview.count > 0 ? (
                <div className="flex flex-col gap-2 max-w-120">
                    <LemonLabel htmlFor="data-deletion-confirmation">
                        Type "{DELETION_CONFIRMATION_TEXT}" to confirm
                    </LemonLabel>
                    <LemonInput
                        id="data-deletion-confirmation"
                        value={confirmationText}
                        onChange={setConfirmationText}
                        placeholder={DELETION_CONFIRMATION_TEXT}
                        autoComplete="off"
                        data-attr="data-deletion-confirmation"
                    />
                </div>
            ) : null}
            {submitError ? <LemonBanner type="error">{submitError}</LemonBanner> : null}
            <div className="flex flex-wrap gap-2">
                <LemonButton
                    type="primary"
                    status="danger"
                    onClick={() => submitRequest()}
                    loading={createdRequestLoading}
                    disabledReason={submitDisabledReason}
                    data-attr="data-deletion-submit"
                >
                    Submit deletion request
                </LemonButton>
                <LemonButton type="secondary" to={urls.settings('environment-data-deletion')}>
                    Cancel
                </LemonButton>
            </div>
        </SceneContent>
    )
}
