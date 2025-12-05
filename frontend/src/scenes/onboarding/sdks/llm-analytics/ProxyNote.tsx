export function ProxyNote(): JSX.Element {
    return (
        <div className="bg-border-light rounded p-4 mt-4 mb-4">
            <h4 className="mb-2">Proxy note</h4>
            <p className="mb-0">
                These SDKs do not proxy your calls. They only fire off an async call to PostHog in the background to
                send the data.
            </p>
        </div>
    )
}
