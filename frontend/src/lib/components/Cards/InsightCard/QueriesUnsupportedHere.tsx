import { XRayHog2 } from 'lib/components/hedgehogs'

export function QueriesUnsupportedHere(): JSX.Element {
    return (
        <div className="text-center">
            <span className="text-muted">
                Query insights are not <strong>yet</strong> supported in this view.
            </span>
            <XRayHog2 className="w-full h-full object-contain" />
        </div>
    )
}
