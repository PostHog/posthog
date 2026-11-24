import { useActions, useValues } from 'kea'

import { QuillUrlConfig } from 'lib/components/IngestionControls/triggers/QuillUrlConfig'
import { replayTriggersLogic } from 'scenes/settings/environment/replayTriggersLogic'

import { QuillSince } from './QuillSince'
import { ReplayUrlAiRegexHelper } from './ReplayUrlAiRegexHelper'

export function QuillUrlTriggerOptions(): JSX.Element {
    const {
        isAddUrlTriggerConfigFormVisible,
        urlTriggerConfig,
        editUrlTriggerIndex,
        isProposedUrlTriggerSubmitting,
        checkUrlTrigger,
        checkUrlTriggerResults,
        urlTriggerInputValidationWarning,
    } = useValues(replayTriggersLogic)
    const {
        addUrlTrigger,
        newUrlTrigger,
        removeUrlTrigger,
        setEditUrlTriggerIndex,
        cancelProposingUrlTrigger,
        setCheckUrlTrigger,
    } = useActions(replayTriggersLogic)

    return (
        <QuillUrlConfig
            logic={replayTriggersLogic}
            logicProps={{}}
            formKey="proposedUrlTrigger"
            validationWarning={urlTriggerInputValidationWarning}
            aiRegexHelper={<ReplayUrlAiRegexHelper addUrl={addUrlTrigger} />}
            title="Enable recordings when URL matches"
            titleBadge={<QuillSince web={{ version: '1.171.0' }} />}
            description="Adding a URL trigger means recording will only be started when the user visits a page that matches the URL."
            checkUrl={checkUrlTrigger}
            checkUrlResults={checkUrlTriggerResults}
            setCheckUrl={setCheckUrlTrigger}
            isAddFormVisible={isAddUrlTriggerConfigFormVisible}
            config={urlTriggerConfig}
            editIndex={editUrlTriggerIndex}
            isSubmitting={isProposedUrlTriggerSubmitting}
            onAdd={newUrlTrigger}
            onCancel={cancelProposingUrlTrigger}
            onEdit={setEditUrlTriggerIndex}
            onRemove={removeUrlTrigger}
        />
    )
}
