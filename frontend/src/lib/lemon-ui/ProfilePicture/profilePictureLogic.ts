import { actions, afterMount, kea, path, reducers } from 'kea'

import type { profilePictureLogicType } from './profilePictureLogicType'

export const profilePictureLogic = kea<profilePictureLogicType>([
    path(['lib', 'lemon-ui', 'ProfilePicture', 'profilePictureLogic']),
    actions({
        setGravatarsReady: true,
    }),
    reducers({
        gravatarsReady: [
            false,
            {
                setGravatarsReady: () => true,
            },
        ],
    }),
    afterMount(({ actions }) => {
        // Defer gravatar loading to prevent blocking initial render (especially in tables)
        // This allows the lettermark fallbacks to render immediately while gravatars load asynchronously
        setTimeout(() => {
            actions.setGravatarsReady()
        }, 0)
    }),
])
