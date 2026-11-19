import { LemonButton } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'

import { shellDocsUrl } from '../../shell/shellNavigation'

const SESSIONS_DOCS_URL = shellDocsUrl({ tab: 'activity', scope: 'sessions' })
// pinned: autocapture dashboards and tests select the link by this value
const TRACES_LINK_DATA_ATTR = 'ai-observability-sessions-setup-traces'

export interface SessionsSetupCardProps {
    /** The traces list, with the filters the sessions scope carries. */
    tracesHref: string
}

export function SessionsSetupCard({ tracesHref }: SessionsSetupCardProps): JSX.Element {
    return (
        <ProductIntroduction
            thingName="session"
            titleOverride="Group traces into sessions"
            description="A session collects the traces of one conversation. Send the same $ai_session_id property on every AI event of a conversation, and its traces show up here as one session."
            actionElementOverride={
                <LemonButton type="primary" to={tracesHref} data-attr={TRACES_LINK_DATA_ATTR}>
                    View traces instead
                </LemonButton>
            }
            docsURL={SESSIONS_DOCS_URL}
            hogLayout="responsive"
            useMainContentContainerQueries
            className="mt-0"
        />
    )
}
