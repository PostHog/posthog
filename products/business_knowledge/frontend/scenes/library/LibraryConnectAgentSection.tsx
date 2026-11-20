import { BindLogic } from 'kea'
import { combineUrl } from 'kea-router'

import { Link } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { connectAgentLogic } from '../settings/connectAgentLogic'
import { useKeyCreationBlocker } from '../settings/useKeyCreationBlocker'
import { LibraryAgentKeys } from './LibraryAgentKeys'

// pinned: setting id from the settings map.
const CONNECT_AGENT_SETTING_URL = combineUrl(
    urls.businessKnowledgeSettings(),
    {},
    { selectedSetting: 'business-knowledge-connect-agent' }
).url

export function LibraryConnectAgentSection({ libraryId }: { libraryId: string }): JSX.Element | null {
    const canConnectAgent = useFeatureFlag('BUSINESS_KNOWLEDGE_MCP')
    const blocker = useKeyCreationBlocker()

    if (!canConnectAgent) {
        return null
    }

    return (
        <SceneSection
            title="Connect an agent"
            description="Create a key that reads only this library, and give it to your agent."
            className="gap-y-2"
        >
            <div className="flex max-w-xl flex-col gap-2">
                {blocker ? (
                    <p className="m-0">{blocker}</p>
                ) : (
                    <BindLogic logic={connectAgentLogic} props={{ libraryId }}>
                        <LibraryAgentKeys />
                    </BindLogic>
                )}
                <p className="m-0 text-secondary">
                    Your agent reads the library through the PostHog MCP server.{' '}
                    <Link to={CONNECT_AGENT_SETTING_URL} data-attr="business-knowledge-library-connect-steps">
                        See how to connect
                    </Link>
                </p>
                <div className="flex flex-wrap items-center gap-1 text-xs text-secondary">
                    <span>Library ID for API and MCP search:</span>
                    <CopyToClipboardInline explicitValue={libraryId} description="library ID" selectable>
                        {libraryId}
                    </CopyToClipboardInline>
                </div>
            </div>
        </SceneSection>
    )
}
