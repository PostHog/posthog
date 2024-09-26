import { LemonButton, Link } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { JSONViewer } from 'lib/components/JSONViewer'
import { Sparkline } from 'lib/components/Sparkline'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { SessionPlayerModal } from 'scenes/session-recordings/player/modal/SessionPlayerModal'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { urls } from 'scenes/urls'

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
            return <JSONViewer src={object} name={null} collapsed={object.length > 10 ? 0 : 1} />
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
            const { openSessionPlayer } = useActions(sessionPlayerModalLogic)
            return (
                <ErrorBoundary>
                    <LemonButton
                        type="primary"
                        size="xsmall"
                        sideIcon={<IconPlayCircle />}
                        data-attr="hog-ql-view-recording-button"
                        {...props}
                        to={urls.replaySingle(sessionId)}
                        onClick={(e) => {
                            e.preventDefault()
                            if (sessionId) {
                                openSessionPlayer({ id: sessionId })
                            }
                        }}
                        className="inline-block"
                    >
                        View recording
                    </LemonButton>
                    <SessionPlayerModal />
                </ErrorBoundary>
            )
        } else if (tag === 'a') {
            const { href, source, target } = rest
            return (
                <ErrorBoundary>
                    <Link to={href} target={target ?? '_self'}>
                        {source ? renderHogQLX(source) : href}
                    </Link>
                </ErrorBoundary>
            )
        } else if (tag === 'strong') {
            const { source } = rest
            return (
                <ErrorBoundary>
                    <strong>{renderHogQLX(source)}</strong>
                </ErrorBoundary>
            )
        } else if (tag === 'em') {
            const { source } = rest
            return (
                <ErrorBoundary>
                    <em>{renderHogQLX(source)}</em>
                </ErrorBoundary>
            )
        }
        return <div>Unknown tag: {String(tag)}</div>
    }

    return <>{String(value)}</>
}
