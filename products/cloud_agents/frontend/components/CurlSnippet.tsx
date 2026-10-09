import { useActions, useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import type { CloudAgentRunCreateApi } from '../generated/api.schemas'
import { CurlSurface, buildRunCurl, cloudAgentsCurlLogic } from '../logics/cloudAgentsCurlLogic'

/** A copyable curl command that starts a run in the current project. */
export function CurlSnippet({ surface, body }: { surface: CurlSurface; body: CloudAgentRunCreateApi }): JSX.Element {
    const { runsUrl } = useValues(cloudAgentsCurlLogic)
    const { reportCurlCopied } = useActions(cloudAgentsCurlLogic)
    return (
        <CodeSnippet language={Language.Bash} wrap thing="curl command" onCopy={() => reportCurlCopied(surface)}>
            {buildRunCurl(runsUrl, body)}
        </CodeSnippet>
    )
}
