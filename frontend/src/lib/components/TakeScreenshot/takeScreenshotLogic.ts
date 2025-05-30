import { actions, kea, listeners, path, reducers } from 'kea'

import type { takeScreenshotLogicType } from './takeScreenshotLogicType'

export const takeScreenshotLogic = kea<takeScreenshotLogicType>([
    path(['lib', 'components', 'TakeScreenshot', 'takeScreenshotLogic']),
    actions({
        setIsOpen: (isOpen: boolean) => ({ isOpen }),
        setImageFile: (imageFile: File | null) => ({ imageFile }),
    }),
    reducers({
        isOpen: [
            false,
            {
                setIsOpen: (_, { isOpen }) => isOpen,
            },
        ],
        imageFile: [
            null,
            {
                setImageFile: (_, { imageFile }) => imageFile,
            },
        ],
    }),
    listeners(() => ({})),
])
