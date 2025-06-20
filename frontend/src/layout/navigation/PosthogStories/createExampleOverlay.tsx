// Simple example overlay helper
export const createExampleOverlay = (
    title: string,
    description: string,
    features?: string[]
): ((closeOverlay: (action?: 'overlay' | 'modal' | 'next') => void) => JSX.Element) => {
    const ExampleOverlay = (closeOverlay: (action?: 'overlay' | 'modal' | 'next') => void): JSX.Element => (
        <div className="p-6 max-w-lg mx-auto text-center">
            <h2 className="text-2xl font-bold mb-2">{title}</h2>
            <p className="text-gray-600 mb-4">{description}</p>
            {features && (
                <ul className="space-y-1 mb-4 text-left">
                    {features.map((f) => (
                        <li key={f} className="flex items-center">
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
                    onClick={() => closeOverlay('next')}
                >
                    Next story
                </button>
                <button
                    className="px-4 py-2 bg-red-600 text-white rounded cursor-pointer"
                    onClick={() => closeOverlay('modal')}
                >
                    Close modal
                </button>
            </div>
        </div>
    )

    ExampleOverlay.displayName = 'ExampleOverlay'
    return ExampleOverlay
}
