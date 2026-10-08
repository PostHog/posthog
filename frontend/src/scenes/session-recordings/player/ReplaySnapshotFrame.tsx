import { CSSProperties, MutableRefObject, useEffect, useRef, useState } from 'react'

import { PLAYER_FRAME_CONTENT_ID, PLAYER_FRAME_SRC } from './playerFrameDocument'

const SNAPSHOT_POLL_MS = 100
// A resource that never finishes must not keep the clickmap from drawing.
const SNAPSHOT_SETTLE_TIMEOUT_MS = 5000

export interface ReplaySnapshotFrameProps {
    /** Inner markup of the replay iframe's <html> element. */
    html: string
    title: string
    /** Sandbox of the frame that renders the snapshot. */
    sandbox: string
    /** Goes on the host frame, which has the same position and size as the snapshot frame. */
    id?: string
    tabIndex?: number
    className?: string
    style?: CSSProperties
    /** Receives the frame that renders the snapshot, not the host frame around it. */
    snapshotRef?: MutableRefObject<HTMLIFrameElement | null>
    onSnapshotLoad?: () => void
}

/**
 * Renders a snapshot of the replayed page. A local-scheme frame (about:srcdoc, about:blank) in the
 * app document gets the app policy, which refuses the fonts and stylesheets of the recorded page.
 * So the snapshot frame goes inside the player frame document and gets the replay frame policy.
 */
export function ReplaySnapshotFrame({
    html,
    title,
    sandbox,
    id,
    tabIndex,
    className,
    style,
    snapshotRef,
    onSnapshotLoad,
}: ReplaySnapshotFrameProps): JSX.Element {
    const hostRef = useRef<HTMLIFrameElement | null>(null)
    const [hostDocument, setHostDocument] = useState<Document | null>(null)
    const onSnapshotLoadRef = useRef(onSnapshotLoad)
    onSnapshotLoadRef.current = onSnapshotLoad

    const handleHostLoad = (): void => {
        const frameDocument = hostRef.current?.contentDocument
        // Firefox fires load for the initial about:blank document too, which has no mount node.
        if (frameDocument?.getElementById(PLAYER_FRAME_CONTENT_ID)) {
            setHostDocument(frameDocument)
        }
    }

    useEffect(() => {
        if (!hostDocument?.body) {
            return
        }
        const snapshot = hostDocument.createElement('iframe')
        snapshot.title = title
        snapshot.setAttribute('sandbox', sandbox)
        if (tabIndex !== undefined) {
            snapshot.tabIndex = tabIndex
        }
        snapshot.style.cssText = 'display: block; width: 100%; height: 100%; border: 0;'
        hostDocument.body.appendChild(snapshot)
        // Written rather than set as srcdoc: WebKit closes the page when a srcdoc frame loads inside
        // this sandboxed host. Nothing written here runs, because the sandbox has no allow-scripts.
        let replaced = false
        let settled = false
        const snapshotWindow = snapshot.contentWindow
        const snapshotDocument = snapshot.contentDocument
        const timers: ReturnType<typeof setTimeout>[] = []
        // Consumers measure the snapshot, so they wait until its stylesheets, images and fonts settle.
        const settle = (): void => {
            if (settled || replaced || !snapshotDocument) {
                return
            }
            settled = true
            // Layout starts the font loads, so fonts.ready waits for them rather than resolving at once.
            void snapshotDocument.body?.offsetHeight
            void (snapshotDocument.fonts?.ready ?? Promise.resolve()).then(() => {
                if (!replaced) {
                    onSnapshotLoadRef.current?.()
                }
            })
        }
        const settleWhenComplete = (): void => {
            if (snapshotDocument?.readyState === 'complete') {
                settle()
            }
        }
        if (snapshotDocument) {
            snapshotDocument.open()
            // document.open() clears the listeners of the document and its window, so they go on after it.
            snapshotDocument.addEventListener('readystatechange', settleWhenComplete)
            snapshotWindow?.addEventListener('load', settle, { once: true })
            snapshotDocument.write(`<!DOCTYPE html><html>${html}</html>`)
            snapshotDocument.close()
            // WebKit completes a written document without firing either event, so it is polled.
            const poll = (): void => {
                settleWhenComplete()
                if (!settled && !replaced) {
                    timers.push(setTimeout(poll, SNAPSHOT_POLL_MS))
                }
            }
            if (snapshotDocument.readyState !== 'complete') {
                timers.push(setTimeout(poll, SNAPSHOT_POLL_MS))
            }
            timers.push(setTimeout(settle, SNAPSHOT_SETTLE_TIMEOUT_MS))
        }
        if (snapshotRef) {
            snapshotRef.current = snapshot
        }
        return () => {
            replaced = true
            timers.forEach(clearTimeout)
            snapshotDocument?.removeEventListener('readystatechange', settleWhenComplete)
            snapshotWindow?.removeEventListener('load', settle)
            snapshot.remove()
            if (snapshotRef?.current === snapshot) {
                snapshotRef.current = null
            }
        }
    }, [hostDocument, html, sandbox, title, tabIndex, snapshotRef])

    return (
        <iframe
            ref={hostRef}
            id={id}
            tabIndex={tabIndex}
            src={PLAYER_FRAME_SRC}
            onLoad={handleHostLoad}
            title={title}
            // The same sandbox as the player frame: the app writes into this document, and nothing runs in it.
            sandbox="allow-same-origin"
            allow=""
            className={className}
            // eslint-disable-next-line react/forbid-dom-props
            style={style}
        />
    )
}
