import React from 'react'

import { IconAI } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { JSONViewer } from 'lib/components/JSONViewer'
import { ExplainCSPViolationButton } from 'lib/components/LLMButton/ExplainCSPViolationButton'
import { Sparkline } from 'lib/components/Sparkline'
import ViewRecordingButton, { RecordingPlayerType } from 'lib/components/ViewRecordingButton/ViewRecordingButton'

import { LightErrorBoundary } from '~/layout/ErrorBoundary/ErrorBoundary'

import { BrandMarkLabel } from 'products/mcp_analytics/frontend/components/BrandMarkLabel'

import { imageDimension, imageSource } from './image'

// NB!!! Sync this list with posthog/hogql/hogqlx.py
// These tags only get the `key` and `children` attributes.
export const HOGQLX_TAGS_NO_ATTRIBUTES = [
    'em',
    'strong',
    'span',
    'div',
    'p',
    'pre',
    'code',
    'h1',
    'h2',
    'h3',
    'h4',
    'h5',
    'h6',
    'ul',
    'ol',
    'li',
    'table',
    'thead',
    'tbody',
    'tr',
    'th',
    'td',
    'blockquote',
    'hr',
    'b',
    'i',
    'u',
]

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

function primitiveString(value: unknown): string | null {
    if (value == null) {
        return ''
    }
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
        return String(value)
    }
    return null
}

export function renderHogQLX(value: any): JSX.Element {
    const object = parseHogQLX(value)

    if (typeof object === 'object') {
        if (Array.isArray(object)) {
            return (
                <>
                    {object.map((obj, index) => (
                        <React.Fragment key={index}>{renderHogQLX(obj)}</React.Fragment>
                    ))}
                </>
            )
        }

        if (object === null) {
            return <></>
        }

        const { __hx_tag: tag, ...rest } = object
        if (!tag) {
            return <JSONViewer src={rest} name={null} collapsed={Object.keys(rest).length > 10 ? 0 : 1} />
        } else if (tag === 'Sparkline') {
            const { data, children, type, ...props } = rest

            return (
                <LightErrorBoundary>
                    <Sparkline className="h-8" {...props} data={data ?? children ?? []} type={type} />
                </LightErrorBoundary>
            )
        } else if (tag === 'ExplainCSPReport') {
            const { properties } = rest

            return (
                <LightErrorBoundary>
                    <ExplainCSPViolationButton
                        properties={properties}
                        label="Explain this CSP violation"
                        type="primary"
                        size="xsmall"
                        sideIcon={<IconAI />}
                        data-attr="hog-ql-explaincsp-button"
                        className="inline-block"
                        disabledReason={
                            properties
                                ? undefined
                                : 'Properties of a $csp_violation event must be provided when asking for an explanation of one'
                        }
                    />
                </LightErrorBoundary>
            )
        } else if (tag === 'RecordingButton') {
            const { sessionId, recordingStatus } = rest

            return (
                <LightErrorBoundary>
                    <ViewRecordingButton
                        openPlayerIn={RecordingPlayerType.Modal}
                        sessionId={sessionId}
                        recordingStatus={recordingStatus}
                        type="primary"
                        size="xsmall"
                        data-attr="hog-ql-view-recording-button"
                        className="inline-block"
                    />
                </LightErrorBoundary>
            )
        } else if (tag === 'BrandMarkLabel') {
            const label = primitiveString(rest.label)
            if (label === null) {
                return <></>
            }
            return (
                <LightErrorBoundary>
                    <BrandMarkLabel label={label} mark={primitiveString(rest.mark) ?? ''} />
                </LightErrorBoundary>
            )
        } else if (tag === 'img') {
            const src = imageSource(rest.src)
            const alt = typeof rest.alt === 'string' ? rest.alt : ''
            if (!src) {
                return <>{alt}</>
            }
            return (
                <img
                    src={src}
                    alt={alt}
                    style={{ width: imageDimension(rest.width), height: imageDimension(rest.height) }}
                    className="inline-block max-w-full object-contain align-middle"
                    loading="lazy"
                    decoding="async"
                />
            )
        } else if (tag === 'a') {
            const { href, children, source, target } = rest
            const value = children ?? source

            return (
                <LightErrorBoundary>
                    <Link to={href} target={target ?? undefined}>
                        {value ? renderHogQLX(value) : href}
                    </Link>
                </LightErrorBoundary>
            )
        } else if (tag === 'blink' || tag === 'marquee' || tag === 'redacted') {
            const { children, source } = rest
            const value = children ?? source
            const renderedChildren = value ? renderHogQLX(value) : ''

            return (
                <LightErrorBoundary>
                    <span className={`hogqlx-${tag}`}>
                        {tag === 'marquee' ? <span>{renderedChildren}</span> : renderedChildren}
                    </span>
                </LightErrorBoundary>
            )
        } else if (HOGQLX_TAGS_NO_ATTRIBUTES.includes(tag)) {
            const { children, source, key } = rest
            const value = children ?? source
            const element = React.createElement(tag, { key: key ?? undefined }, value ? renderHogQLX(value) : undefined)

            return <LightErrorBoundary>{element}</LightErrorBoundary>
        }

        return <div>Unknown tag: {String(tag)}</div>
    }

    return <>{String(value)}</>
}
