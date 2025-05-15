export function EmptyState(): JSX.Element {
    return (
        <div className="text-primary flex flex-col items-center justify-center h-full text-center px-4 mt-16">
            <span className="font-semibold text-lg mb-2">Welcome to Chat with your customers</span>
            <span>
                When your customers text you via the widget or other sources (Zendesk, Intercom, etc.), their chats will
                appear here.
            </span>
        </div>
    )
}
