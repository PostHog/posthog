import { useActions, useValues } from 'kea'

import { QuillUrlConfig } from 'lib/components/IngestionControls/triggers/QuillUrlConfig'
import { replayTriggersLogic } from 'scenes/settings/environment/replayTriggersLogic'

import { ReplayUrlAiRegexHelper } from './ReplayUrlAiRegexHelper'

export function QuillUrlBlocklistOptions(): JSX.Element {
    const {
        isAddUrlBlocklistConfigFormVisible,
        urlBlocklistConfig,
        editUrlBlocklistIndex,
        isProposedUrlBlocklistSubmitting,
        checkUrlBlocklist,
        checkUrlBlocklistResults,
        urlBlocklistInputValidationWarning,
    } = useValues(replayTriggersLogic)
    const {
        addUrlBlocklist,
        newUrlBlocklist,
        removeUrlBlocklist,
        setEditUrlBlocklistIndex,
        cancelProposingUrlBlocklist,
        setCheckUrlBlocklist,
    } = useActions(replayTriggersLogic)

    return (
        <QuillUrlConfig
            logic={replayTriggersLogic}
            logicProps={{}}
            formKey="proposedUrlBlocklist"
            validationWarning={urlBlocklistInputValidationWarning}
            aiRegexHelper={<ReplayUrlAiRegexHelper addUrl={addUrlBlocklist} />}
            title="Pause recordings when URL matches"
            description="Pause recordings while the user is on a page that matches the URL."
            checkUrl={checkUrlBlocklist}
            checkUrlResults={checkUrlBlocklistResults}
            setCheckUrl={setCheckUrlBlocklist}
            isAddFormVisible={isAddUrlBlocklistConfigFormVisible}
            config={urlBlocklistConfig}
            editIndex={editUrlBlocklistIndex}
            isSubmitting={isProposedUrlBlocklistSubmitting}
            onAdd={newUrlBlocklist}
            onCancel={cancelProposingUrlBlocklist}
            onEdit={setEditUrlBlocklistIndex}
            onRemove={removeUrlBlocklist}
        />
    )
}
