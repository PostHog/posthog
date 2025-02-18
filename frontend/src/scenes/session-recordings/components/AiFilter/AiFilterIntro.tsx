import { FilmCameraHog } from 'lib/components/hedgehogs'

export function AiFilterIntro(): JSX.Element {
    return (
        <>
            <div className="flex">
                <FilmCameraHog className="w-20 h-20" />
            </div>
            <div className="text-center mb-3">
                <h2 className="text-2xl font-bold mb-2 text-balance">Chat with your recordings</h2>
                <div className="text-secondary text-balance">
                    I'm Max, here to help you to find recordings matching your needs.
                </div>
            </div>
        </>
    )
}
