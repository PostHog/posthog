import { XRayHog2 } from 'lib/components/hedgehogs'

export function QueriesUnsupportedHere(): JSX.Element {
    return (
        <div className="text-center">
            <span className="text-muted">
                Not all Query types are supported in this view <strong>yet</strong>.
            </span>
            <XRayHog2 className="w-full h-full object-contain" />
        </div>
    )
}
