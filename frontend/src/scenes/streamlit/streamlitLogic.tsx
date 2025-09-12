import { actions, kea, path, props, reducers, selectors } from 'kea'
import { afterMount } from 'kea'

import type { streamlitLogicType } from './streamlitLogicType'

export interface StreamlitLogicProps {
    // Add any props your logic needs
}

export const streamlitLogic = kea<streamlitLogicType>([
    path(['scenes', 'streamlit', 'streamlitLogic']),
    props({} as StreamlitLogicProps),

    actions({
        // Add your actions here
        setLoading: (loading: boolean) => ({ loading }),
    }),

    reducers({
        isLoading: [
            false,
            {
                setLoading: (_, { loading }) => loading,
            },
        ],
    }),

    selectors({
        // Add your selectors here
    }),

    afterMount(() => {
        // Initialize any data loading here if needed
    }),
])
