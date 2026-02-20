import { SessionRecordingPlaylistLogicProps } from '../playlist/sessionRecordingsPlaylistLogic'

export function SessionRecordingsPlaylistRedesign({}: SessionRecordingPlaylistLogicProps): JSX.Element {
    return (
        <div className="w-full h-full flex flex-col">
            {/* Placeholder for development */}
            <div className="flex flex-col items-center justify-center min-h-96 p-8 text-center bg-surface-secondary border-2 border-dashed border-border-primary rounded m-8">
                <h2 className="text-lg font-semibold mb-4">Session Replay Redesign</h2>
                <p className="mb-2 max-w-xl">Placeholder behind flag...</p>
            </div>
        </div>
    )
}
