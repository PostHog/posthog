import '@testing-library/jest-dom'

import { fireEvent, render } from '@testing-library/react'
import { createRef, MutableRefObject } from 'react'

import { ReplaySnapshotFrame } from './ReplaySnapshotFrame'

describe('ReplaySnapshotFrame', () => {
    it('mounts the snapshot inside the player frame document, not the app document', () => {
        const snapshotRef = createRef<HTMLIFrameElement>() as MutableRefObject<HTMLIFrameElement | null>
        const onSnapshotLoad = jest.fn()
        const { container } = render(
            <ReplaySnapshotFrame
                html="<body>recorded page</body>"
                title="Snapshot"
                sandbox="allow-same-origin"
                snapshotRef={snapshotRef}
                onSnapshotLoad={onSnapshotLoad}
            />
        )
        const host = container.querySelector('iframe')!
        expect(host).toHaveAttribute('src', '/replay_player_frame/index.html')
        expect(host).not.toHaveAttribute('srcdoc')

        const hostDocument = host.contentDocument!
        hostDocument.open()
        hostDocument.write('<div id="player-frame-content"></div>')
        hostDocument.close()
        fireEvent.load(host)

        const snapshot = snapshotRef.current!
        expect(snapshot.ownerDocument).toBe(hostDocument)
        expect(snapshot).toHaveAttribute('srcdoc', '<body>recorded page</body>')
        expect(snapshot).toHaveAttribute('sandbox', 'allow-same-origin')

        fireEvent.load(snapshot)
        expect(onSnapshotLoad).toHaveBeenCalledTimes(1)
    })
})
