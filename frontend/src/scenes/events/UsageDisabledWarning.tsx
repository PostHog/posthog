import { AlertMessage } from 'lib/components/AlertMessage'

export function UsageDisabledWarning(): JSX.Element {
    return (
        <AlertMessage type="info">
            <div className="text-base mb-1">Event usage information is not enabled for your instance.</div>
            <p className="font-normal">
                You will still see the list of events and properties, but usage information will be unavailable. If you
                want to enable event usage please set the follow environment variable:{' '}
                <pre style={{ display: 'inline' }}>ASYNC_EVENT_PROPERTY_USAGE=1</pre>. Please note, enabling this
                environment variable <b>may increase load considerably in your infrastructure</b>, particularly if you
                have a large volume of events.
            </p>
        </AlertMessage>
    )
}
