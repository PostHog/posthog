import { applyAiRegex } from 'lib/components/IngestionControls/triggers/UrlConfig'
import { UrlTriggerConfig } from 'lib/components/IngestionControls/types'
import { AiRegexHelper, AiRegexHelperButton } from 'scenes/session-recordings/components/AiRegexHelper/AiRegexHelper'

export function ReplayUrlAiRegexHelper({
    addUrl,
}: {
    addUrl: (urlTriggerConfig: UrlTriggerConfig) => void
}): JSX.Element {
    return (
        <>
            <AiRegexHelper onApply={(regex) => applyAiRegex(regex, addUrl)} />
            <AiRegexHelperButton />
        </>
    )
}
