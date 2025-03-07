import { Link } from '@posthog/lemon-ui'
import { JSONViewer } from 'lib/components/JSONViewer'
import { Sparkline } from 'lib/components/Sparkline'
import ViewRecordingButton from 'lib/components/ViewRecordingButton/ViewRecordingButton'

import { ErrorBoundary } from '~/layout/ErrorBoundary'

export function parseHogQLX(value: any): any {
    if (!Array.isArray(value)) {
        return value
    }
    if (value[0] === '__hx_tag') {
        const object: Record<string, any> = {}
        const start = value[1] === '__hx_obj' ? 2 : 0
        for (let i = start; i < value.length; i += 2) {
            const key = parseHogQLX(value[i])
            object[key] = parseHogQLX(value[i + 1])
        }
        return object
    }
    return value.map((v) => parseHogQLX(v))
}

export function renderHogQLX(value: any): JSX.Element {
    const object = parseHogQLX(value)

    if (typeof object === 'object') {
        if (Array.isArray(object)) {
            return <>{object.map((obj) => renderHogQLX(obj))}</>
        }

        const { __hx_tag: tag, ...rest } = object
        if (!tag) {
            return <JSONViewer src={rest} name={null} collapsed={Object.keys(rest).length > 10 ? 0 : 1} />
        } else if (tag === 'Sparkline') {
            const { data, type, ...props } = rest
            return (
                <ErrorBoundary>
                    <Sparkline className="h-8" {...props} data={data ?? []} type={type} />
                </ErrorBoundary>
            )
        } else if (tag === 'RecordingButton') {
            const { sessionId, ...props } = rest
            return (
                <ErrorBoundary>
                    <ViewRecordingButton
                        inModal
                        sessionId={sessionId}
                        type="primary"
                        size="xsmall"
                        data-attr="hog-ql-view-recording-button"
                        className="inline-block"
                        {...props}
                        disabledReason={sessionId ? undefined : 'No session id associated with this event'}
                    />
                </ErrorBoundary>
            )
        } else if (tag === 'a') {
            const { href, children, source, target } = rest
            return (
                <ErrorBoundary>
                    <Link to={href} target={target ?? undefined}>
                        {children ?? source ? renderHogQLX(children ?? source) : href}
                    </Link>
                </ErrorBoundary>
            )
        } else if (tag === 'strong') {
            return (
                <ErrorBoundary>
                    <strong>{renderHogQLX(rest.children ?? rest.source)}</strong>
                </ErrorBoundary>
            )
        } else if (tag === 'em') {
            return (
                <ErrorBoundary>
                    <em>{renderHogQLX(rest.children ?? rest.source)}</em>
                </ErrorBoundary>
            )
        }
        return <div>Unknown tag: {String(tag)}</div>
    }

    return <>{String(value)}</>
}
