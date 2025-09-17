import { CloseOverlayAction } from './storiesMap'

interface ExampleOverlayComponentProps {
    closeOverlay: (action?: CloseOverlayAction) => void
}

export const ExampleOverlayComponent = ({ closeOverlay }: ExampleOverlayComponentProps): JSX.Element => {
    return (
        <div className="flex items-center justify-center h-full bg-white p-8">
            <div className="text-center flex flex-col gap-2">
                <h2 className="text-2xl font-bold mb-4">Custom Component Placeholder</h2>
                <p className="text-gray-600 mb-6">Add your custom component code here</p>

                <div className="flex gap-2">
                    <button
                        onClick={() => closeOverlay(CloseOverlayAction.Previous)}
                        className="px-4 py-2 bg-yellow-500 text-white rounded hover:bg-yellow-700"
                    >
                        Previous story
                    </button>
                    <button
                        onClick={() => closeOverlay(CloseOverlayAction.Next)}
                        className="px-4 py-2 bg-orange-500 text-white rounded hover:bg-orange-700"
                    >
                        Next story
                    </button>
                    <button
                        onClick={() => closeOverlay(CloseOverlayAction.Overlay)}
                        className="px-4 py-2 bg-orange-500 text-white rounded hover:bg-orange-700"
                    >
                        Continue story
                    </button>
                    <button
                        onClick={() => closeOverlay(CloseOverlayAction.Modal)}
                        className="px-4 py-2 bg-red-500 text-white rounded hover:bg-red-700"
                    >
                        Close modal
                    </button>
                </div>
            </div>
        </div>
    )
}
