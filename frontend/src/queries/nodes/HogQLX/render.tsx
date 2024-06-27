import { JSONViewer } from 'lib/components/JSONViewer'
import { Sparkline } from 'lib/lemon-ui/Sparkline'

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

    if (typeof object === 'object' && !Array.isArray(object)) {
        const tag = object.__hx_tag ?? null

        if (tag === null) {
            return <JSONViewer src={object} name={null} collapsed={Object.keys(object).length > 10 ? 0 : 1} />
        } else if (tag === 'Sparkline') {
            const { data, type } = object
            return (
                <ErrorBoundary>
                    <Sparkline data={data ?? []} type={type ?? []} {...object} />
                </ErrorBoundary>
            )
        }
        return <div>Unknown tag: {String(tag)}</div>
    }

    return <>{String(value)}</>
}
