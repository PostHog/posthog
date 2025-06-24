import { CloseOverlayAction } from './storiesMap'

// Simple example overlay helper
export const createExampleOverlay = (
    title: string,
    description: string,
    features?: string[]
): ((closeOverlay: (action?: CloseOverlayAction) => void) => JSX.Element) => {
    const ExampleOverlay = (closeOverlay: (action?: CloseOverlayAction) => void): JSX.Element => (
        <div className="p-6 max-w-lg mx-auto text-center">
            <h2 className="text-2xl font-bold mb-2">{title}</h2>
            <p className="text-gray-600 mb-4">{description}</p>
            {features && (
                <ul className="space-y-1 mb-4 text-left">
                    {features.map((f, index) => (
                        <li key={index} className="flex items-center">
                            <span className="text-green-500 mr-2">✓</span>
                            {f}
                        </li>
                    ))}
                </ul>
            )}
            <div className="flex gap-2 justify-center">
                <button
                    className="px-4 py-2 bg-red-600 text-white rounded cursor-pointer"
                    onClick={() => closeOverlay()}
                >
                    Continue story
                </button>
                <button
                    className="px-4 py-2 bg-red-600 text-white rounded cursor-pointer"
                    onClick={() => closeOverlay(CloseOverlayAction.Next)}
                >
                    Next story
                </button>
                <button
                    className="px-4 py-2 bg-red-600 text-white rounded cursor-pointer"
                    onClick={() => closeOverlay(CloseOverlayAction.Previous)}
                >
                    Previous story
                </button>
                <button
                    className="px-4 py-2 bg-red-600 text-white rounded cursor-pointer"
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
