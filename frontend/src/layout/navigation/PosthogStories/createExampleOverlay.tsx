import { CloseOverlayAction } from './storiesMap'

// Simple example overlay helper
export const createExampleOverlay = (
    title: string,
    description: string,
    features?: string[]
): ((closeOverlay: (action?: CloseOverlayAction) => void) => JSX.Element) => {
    const ExampleOverlay = (closeOverlay: (action?: CloseOverlayAction) => void): JSX.Element => (
        <div className="mx-auto max-w-lg p-6 text-center">
            <h2 className="mb-2 text-2xl font-bold">{title}</h2>
            <p className="mb-4 text-gray-600">{description}</p>
            {features && (
                <ul className="mb-4 space-y-1 text-left">
                    {features.map((f, index) => (
                        <li key={index} className="flex items-center">
                            <span className="mr-2 text-green-500">✓</span>
                            {f}
                        </li>
                    ))}
                </ul>
            )}
            <div className="flex justify-center gap-2">
                <button
                    className="cursor-pointer rounded bg-red-600 px-4 py-2 text-white"
                    onClick={() => closeOverlay()}
                >
                    Continue story
                </button>
                <button
                    className="cursor-pointer rounded bg-red-600 px-4 py-2 text-white"
                    onClick={() => closeOverlay(CloseOverlayAction.Next)}
                >
                    Next story
                </button>
                <button
                    className="cursor-pointer rounded bg-red-600 px-4 py-2 text-white"
                    onClick={() => closeOverlay(CloseOverlayAction.Previous)}
                >
                    Previous story
                </button>
                <button
                    className="cursor-pointer rounded bg-red-600 px-4 py-2 text-white"
                    onClick={() => closeOverlay(CloseOverlayAction.Modal)}
                >
                    Close modal
                </button>
            </div>
        </div>
    )

    ExampleOverlay.displayName = 'ExampleOverlay'
    return ExampleOverlay
}
