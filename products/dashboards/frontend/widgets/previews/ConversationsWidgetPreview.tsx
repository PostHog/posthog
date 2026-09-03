import { conversationsSampleTickets } from '../../components/WidgetCard/widgetOverviewStoryFixtures'
import { ConversationsWidget } from '../conversations/ConversationsWidget'

export function ConversationsWidgetPreview(): JSX.Element {
    return (
        <div className="shadow-sm">
            <ConversationsWidget
                tileId={0}
                config={{ limit: 3 }}
                loading={false}
                result={{ results: conversationsSampleTickets.slice(0, 3) }}
            />
        </div>
    )
}
