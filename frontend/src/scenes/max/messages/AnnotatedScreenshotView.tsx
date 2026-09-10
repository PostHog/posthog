interface ScreenshotMarker {
    n: number
    kind: 'rage' | 'click'
    count: number
}

export interface AnnotatedScreenshotData {
    imageB64: string
    markers: ScreenshotMarker[]
}

export function parseAnnotatedScreenshot(screenshot: unknown): AnnotatedScreenshotData | null {
    if (!screenshot || typeof screenshot !== 'object') {
        return null
    }
    const { image_b64, markers } = screenshot as { image_b64?: unknown; markers?: unknown }
    if (typeof image_b64 !== 'string' || !image_b64 || !Array.isArray(markers)) {
        return null
    }
    return { imageB64: image_b64, markers: markers.filter(isScreenshotMarker) }
}

function isScreenshotMarker(marker: unknown): marker is ScreenshotMarker {
    if (!marker || typeof marker !== 'object') {
        return false
    }
    const { n, kind, count } = marker as Record<string, unknown>
    return typeof n === 'number' && typeof count === 'number' && (kind === 'rage' || kind === 'click')
}

function legend(markers: ScreenshotMarker[]): string {
    return markers.map((m) => `#${m.n} ${m.kind === 'rage' ? 'rage clicks' : 'clicks'} (${m.count}×)`).join(', ')
}

export function AnnotatedScreenshotView({ data }: { data: AnnotatedScreenshotData }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <img
                src={`data:image/jpeg;base64,${data.imageB64}`}
                alt="Page screenshot with numbered markers on the click and rage-click hot spots"
                className="max-w-full rounded border"
            />
            {data.markers.length > 0 && (
                <span className="text-xs text-muted">Hot spots on this page: {legend(data.markers)}</span>
            )}
        </div>
    )
}
